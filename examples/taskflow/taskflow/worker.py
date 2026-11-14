"""Worker threads that execute jobs, and the scheduler that repairs leases."""
from __future__ import annotations

import logging
import threading

from .events import EventBus
from .pipeline import Pipeline, PipelineOutcome
from .storage import Job, JobState, Storage

log = logging.getLogger(__name__)


class LeaseKeeper(threading.Thread):
    """Extend a job lease while its pipeline is running."""

    def __init__(self, storage: Storage, job_id: int, worker_id: str,
                 lease_seconds: float) -> None:
        super().__init__(name=f"lease-{worker_id}-{job_id}", daemon=True)
        self.storage = storage
        self.job_id = job_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()

    def run(self) -> None:
        interval = max(0.2, self.lease_seconds / 3)
        while not self._stop.wait(interval):
            if not self.storage.heartbeat(self.job_id, self.worker_id,
                                          self.lease_seconds):
                return

    def stop(self) -> None:
        self._stop.set()


class Worker(threading.Thread):
    def __init__(self, name: str, storage: Storage, pipeline: Pipeline,
                 bus: EventBus, stop_event: threading.Event,
                 poll_seconds: float, lease_seconds: float) -> None:
        super().__init__(name=name, daemon=True)
        self.storage = storage
        self.pipeline = pipeline
        self.bus = bus
        self.stop_event = stop_event
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds

    def run(self) -> None:
        log.info("worker %s started", self.name)
        while not self.stop_event.is_set():
            if not self.run_once():
                self.stop_event.wait(self.poll_seconds)
        log.info("worker %s stopped", self.name)

    def run_once(self) -> bool:
        job = self.storage.claim_next(self.name, self.lease_seconds)
        if job is None:
            return False
        self._process(job)
        return True

    def _process(self, job: Job) -> None:
        self.bus.publish("job.started", {
            "job_id": job.id, "kind": job.kind, "worker": self.name,
            "attempt": job.attempts,
        })
        keeper = LeaseKeeper(self.storage, job.id, self.name, self.lease_seconds)
        keeper.start()
        try:
            outcome = self.pipeline.execute(job)
        except Exception as error:
            log.exception("pipeline crashed for job %s", job.id)
            outcome = PipelineOutcome(False, error=f"{type(error).__name__}: {error}")
        finally:
            keeper.stop()
            keeper.join(timeout=1.0)
        self._finish(job, outcome)

    def _finish(self, job: Job, outcome: PipelineOutcome) -> None:
        state = JobState.SUCCEEDED if outcome.ok else JobState.FAILED
        stored = self.storage.finish_job(job.id, self.name, state,
                                        outcome.output, outcome.error)
        if not stored:
            self.bus.publish("job.lost", {"job_id": job.id, "worker": self.name})
            log.warning("job %s was lost by worker %s", job.id, self.name)
            return
        payload = {
            "job_id": job.id,
            "kind": job.kind,
            "worker": self.name,
            "attempts": job.attempts,
            "error": outcome.error,
            "output": outcome.output,
            "steps": [
                {"name": step.name, "attempts": step.attempts,
                 "ok": step.ok, "duration": round(step.duration, 4)}
                for step in outcome.steps
            ],
        }
        self.bus.publish("job.succeeded" if outcome.ok else "job.failed", payload)


class Scheduler(threading.Thread):
    def __init__(self, storage: Storage, bus: EventBus,
                 stop_event: threading.Event, interval: float,
                 retention_seconds: float) -> None:
        super().__init__(name="scheduler", daemon=True)
        self.storage = storage
        self.bus = bus
        self.stop_event = stop_event
        self.interval = interval
        self.retention_seconds = retention_seconds

    def run(self) -> None:
        log.info("scheduler started")
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            self.stop_event.wait(self.interval)
        log.info("scheduler stopped")

    def tick(self) -> None:
        requeued = self.storage.requeue_expired()
        failed = self.storage.fail_exhausted()
        pruned = self.storage.prune(self.retention_seconds)
        if requeued:
            self.bus.publish("scheduler.requeued", {"job_ids": requeued})
        if failed:
            self.bus.publish("scheduler.failed", {"job_ids": failed})
        if pruned:
            self.bus.publish("scheduler.pruned", {"count": pruned})

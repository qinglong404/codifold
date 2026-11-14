"""Resolve a job kind to registered steps and execute them with retries."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .registry import StepSpec
from .storage import Job, Storage


PIPELINES: dict[str, tuple[str, ...]] = {
    "report": ("csv.import", "report.summarize", "notify.webhook"),
    "maintenance": ("maintenance.prune",),
}


class UnknownPipeline(ValueError):
    pass


@dataclass(slots=True)
class StepOutcome:
    name: str
    attempts: int
    ok: bool
    duration: float
    output: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class PipelineOutcome:
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    steps: list[StepOutcome] = field(default_factory=list)
    error: str | None = None


class Pipeline:
    def __init__(self, steps: dict[str, StepSpec], storage: Storage | None = None) -> None:
        self.steps = dict(steps)
        self.storage = storage
        self.plans = dict(PIPELINES)

    def plan_for(self, kind: str) -> tuple[str, ...]:
        try:
            return self.plans[kind]
        except KeyError:
            raise UnknownPipeline(f"未知任务类型：{kind}") from None

    def execute(self, job: Job) -> PipelineOutcome:
        try:
            plan = self.plan_for(job.kind)
        except UnknownPipeline as error:
            return PipelineOutcome(False, error=str(error))
        outputs: dict[str, Any] = {}
        steps: list[StepOutcome] = []
        context = {
            "job": job,
            "payload": job.payload,
            "outputs": outputs,
            "storage": self.storage,
        }
        for name in plan:
            spec = self.steps.get(name)
            if spec is None:
                error = f"步骤未注册：{name}"
                steps.append(StepOutcome(name, 0, False, 0.0, error=error))
                return PipelineOutcome(False, {"steps": outputs, "merged": {}},
                                       steps, error)
            outcome = self._run_step(spec, context)
            steps.append(outcome)
            if not outcome.ok:
                error = f"{name}: {outcome.error}" if outcome.error else f"步骤失败：{name}"
                return PipelineOutcome(False, {"steps": outputs, "merged": {}},
                                       steps, error)
            outputs[name] = outcome.output or {}
        merged: dict[str, Any] = {}
        for output in outputs.values():
            merged.update(output)
        return PipelineOutcome(True, {"steps": outputs, "merged": merged}, steps)

    def _run_step(self, spec: StepSpec, context: dict[str, Any]) -> StepOutcome:
        started = time.monotonic()
        attempts_allowed = spec.retries + 1
        last_error = ""
        for attempt in range(1, attempts_allowed + 1):
            try:
                output = spec.handler(dict(context))
                if not isinstance(output, dict):
                    raise TypeError("步骤必须返回 dict")
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                if attempt < attempts_allowed:
                    time.sleep(spec.backoff * (2 ** (attempt - 1)))
                    continue
                return StepOutcome(spec.name, attempt, False,
                                   time.monotonic() - started, error=last_error)
            return StepOutcome(spec.name, attempt, True,
                               time.monotonic() - started, output=output)
        return StepOutcome(spec.name, attempts_allowed, False,
                           time.monotonic() - started, error=last_error or "未知错误")

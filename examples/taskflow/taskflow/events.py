"""A tiny synchronous event bus shared by workers and plugins."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any


EventHandler = Callable[[str, dict[str, Any]], None]


class EventBus:
    """Deliver topic events to subscribers without letting one handler break the rest."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        with self._lock:
            self._handlers[topic].append(handler)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock:
            handlers = list(self._handlers.get(topic, ()))
            handlers.extend(self._handlers.get("*", ()))
        for handler in handlers:
            try:
                handler(topic, payload)
            except Exception:
                logging.getLogger(__name__).exception(
                    "event handler failed: topic=%s handler=%s", topic, handler.__name__
                )

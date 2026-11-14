"""Decorator-based step and subscriber registry filled by plugin imports."""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .events import EventBus


StepHandler = Callable[[dict[str, Any]], dict[str, Any]]
Subscriber = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class StepSpec:
    name: str
    handler: StepHandler
    retries: int
    backoff: float
    description: str


_STEPS: dict[str, StepSpec] = {}
_SUBSCRIBERS: list[tuple[str, Subscriber]] = []
_LOADED_PACKAGES: set[str] = set()


def step(name: str, *, retries: int = 0, backoff: float = 0.0,
         description: str = "") -> Callable[[StepHandler], StepHandler]:
    """Register a pipeline step by name."""
    def decorate(handler: StepHandler) -> StepHandler:
        if name in _STEPS:
            raise ValueError(f"重复注册步骤：{name}")
        if retries < 0 or backoff < 0:
            raise ValueError("retries 和 backoff 不能为负数")
        _STEPS[name] = StepSpec(name, handler, retries, backoff,
                                description or (handler.__doc__ or "").strip())
        return handler
    return decorate


def on(topic: str) -> Callable[[Subscriber], Subscriber]:
    """Register a subscriber that the plugin loader attaches to the event bus."""
    def decorate(handler: Subscriber) -> Subscriber:
        _SUBSCRIBERS.append((topic, handler))
        return handler
    return decorate


def registered_steps() -> dict[str, StepSpec]:
    return dict(_STEPS)


def step_names() -> list[str]:
    return sorted(_STEPS)


def load_plugins(package: str, bus: EventBus) -> list[str]:
    """Import every module in *package*, then attach registered subscribers."""
    if package in _LOADED_PACKAGES:
        return step_names()
    module = importlib.import_module(package)
    for info in pkgutil.iter_modules(module.__path__):
        importlib.import_module(f"{package}.{info.name}")
    for topic, handler in _SUBSCRIBERS:
        bus.subscribe(topic, handler)
    _LOADED_PACKAGES.add(package)
    return step_names()

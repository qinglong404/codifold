"""Configuration loading for the taskflow demo service."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Settings:
    database: Path = Path("taskflow.db")
    host: str = "127.0.0.1"
    port: int = 8765
    workers: int = 2
    lease_seconds: float = 30.0
    poll_seconds: float = 0.5
    scheduler_seconds: float = 5.0
    retention_seconds: float = 3600.0
    api_token: str | None = None
    log_level: str = "INFO"
    plugin_package: str = "taskflow.plugins"


def _coerce(default: Any, raw: Any) -> Any:
    if isinstance(default, bool):
        return bool(raw)
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, Path):
        return Path(str(raw)).expanduser()
    return str(raw)


def validate_settings(settings: Settings) -> Settings:
    """Return a normalized copy or raise ValueError for unsafe values."""
    if not 1 <= settings.port <= 65535:
        raise ValueError("port 必须在 1–65535 之间")
    if settings.workers < 1:
        raise ValueError("workers 至少为 1")
    if settings.lease_seconds <= 0 or settings.poll_seconds <= 0:
        raise ValueError("lease_seconds 和 poll_seconds 必须大于 0")
    if settings.scheduler_seconds <= 0 or settings.retention_seconds < 0:
        raise ValueError("scheduler_seconds 必须大于 0，retention_seconds 不能为负")
    level = settings.log_level.upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"未知日志级别：{settings.log_level}")
    token = settings.api_token or None
    return replace(settings, log_level=level, api_token=token)


def load_settings(config_path: str | None = None,
                  env: Mapping[str, str] | None = None) -> Settings:
    """Load defaults, then a JSON file, then TASKFLOW_* environment values."""
    env = os.environ if env is None else env
    values: dict[str, Any] = {}
    if config_path:
        path = Path(config_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"配置文件不存在：{path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("配置文件必须是 JSON 对象")
        values.update({key: value for key, value in data.items() if value is not None})
    defaults = Settings()
    for key in defaults.__dataclass_fields__:
        env_key = f"TASKFLOW_{key.upper()}"
        if env_key in env:
            values[key] = env[env_key]
    unknown = sorted(set(values) - set(defaults.__dataclass_fields__))
    if unknown:
        raise ValueError(f"未知配置项：{', '.join(unknown)}")
    values = {key: _coerce(getattr(defaults, key), value)
              for key, value in values.items()}
    return validate_settings(replace(defaults, **values))

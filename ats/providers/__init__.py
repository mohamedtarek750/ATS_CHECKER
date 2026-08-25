"""Provider registry. Add a backend here and the rest of the system picks it up."""

from __future__ import annotations

import threading

from ..config import DEFAULT_MODELS, DEFAULT_WORKERS, PROVIDER_NAMES
from .base import (
    ClassificationError,
    DailyQuotaExhausted,
    FatalScreeningError,
    Provider,
    RateLimiter,
)
from .claude import ClaudeProvider
from .gemini import GeminiProvider

PROVIDER_CLASSES: dict[str, type[Provider]] = {
    "gemini": GeminiProvider,
    "claude": ClaudeProvider,
    "anthropic": ClaudeProvider,   # alias
}

_instances: dict[str, Provider] = {}
_lock = threading.Lock()


def provider_names() -> list[str]:
    """Canonical provider keys, without the aliases."""
    return list(PROVIDER_NAMES)


def get_provider(name: str) -> Provider:
    """Return the shared instance for `name`. Raises KeyError if unknown."""
    key = (name or "").strip().lower()
    if key not in PROVIDER_CLASSES:
        raise KeyError(
            f"Unknown provider '{name}'. Available: {', '.join(provider_names())}"
        )
    with _lock:
        if key not in _instances:
            _instances[key] = PROVIDER_CLASSES[key]()
        return _instances[key]


__all__ = [
    "DEFAULT_MODELS",
    "DEFAULT_WORKERS",
    "ClassificationError",
    "DailyQuotaExhausted",
    "FatalScreeningError",
    "Provider",
    "RateLimiter",
    "get_provider",
    "provider_names",
]

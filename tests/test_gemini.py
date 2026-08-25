"""Offline checks for the Gemini backend. No API key and no network needed.

Covers the three things that can silently break it: the Verdict schema surviving
conversion to Gemini's format, account-level errors being recognised as fatal, and
the rate limiter actually spacing requests out.

Run: python tests/test_gemini.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats.config import DEFAULT_MODELS, Settings  # noqa: E402
from ats.providers import get_provider  # noqa: E402
from ats.providers.base import (  # noqa: E402
    ClassificationError,
    FatalScreeningError,
    RateLimiter,
)
from ats.schema import Verdict  # noqa: E402


class FakeAPIError(Exception):
    """Stands in for google.genai.errors.APIError, which needs a live response."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def test_verdict_schema_converts_for_gemini():
    """Every field, and the 36-role enum, must survive Gemini's schema conversion."""
    from google.genai import _transformers as transformers

    schema = transformers.t_schema(None, Verdict).model_dump(exclude_none=True)
    properties = schema["properties"]

    assert len(properties) == len(Verdict.model_fields)
    assert len(schema["required"]) == len(Verdict.model_fields), "all fields required"

    roles = properties["role_family"]["enum"]
    assert "Data Scientist" in roles and "Undetermined" in roles
    assert len(roles) == 36

    assert properties["seniority"]["enum"][0] == "Student"
    assert properties["suggested_reject_reason"]["enum"][0] == "none"
    assert properties["top_skills"]["type"] == "ARRAY"
    assert properties["ai_generated_score"]["type"] == "INTEGER"


def test_no_credits_style_errors_are_fatal():
    provider = get_provider("gemini")
    fatal_cases = [
        FakeAPIError("API key not valid. Please pass a valid API key.", 400),
        FakeAPIError("PERMISSION_DENIED: caller lacks permission", 403),
        FakeAPIError("models/nope is not found for API version v1beta", 404),
    ]
    for exc in fatal_cases:
        mapped = provider._classify_error(exc)
        assert isinstance(mapped, FatalScreeningError), exc


def test_daily_quota_is_fatal_but_burst_is_not():
    provider = get_provider("gemini")

    daily = FakeAPIError(
        "RESOURCE_EXHAUSTED: Quota exceeded for GenerateRequestsPerDayPerProject", 429
    )
    assert isinstance(provider._classify_error(daily), FatalScreeningError)
    assert not provider._is_retryable(daily), "a spent day will not recover on retry"

    burst = FakeAPIError("RESOURCE_EXHAUSTED: too many requests per minute", 429)
    mapped = provider._classify_error(burst)
    assert isinstance(mapped, ClassificationError)
    assert not isinstance(mapped, FatalScreeningError), "a burst is per-file, not fatal"
    assert provider._is_retryable(burst)


def test_server_errors_retry_and_client_errors_do_not():
    provider = get_provider("gemini")
    assert provider._is_retryable(FakeAPIError("internal error", 500))
    assert provider._is_retryable(FakeAPIError("unavailable", 503))
    assert not provider._is_retryable(FakeAPIError("bad request", 400))


def test_rate_limiter_spaces_requests_out():
    """Four calls at 120/min must take at least three intervals in total."""
    limiter = RateLimiter(requests_per_minute=120)  # 0.5s apart
    started = time.monotonic()
    threads = [threading.Thread(target=limiter.wait) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started
    assert elapsed >= 1.4, f"expected >=1.5s of spacing, got {elapsed:.2f}s"


def test_rate_limiter_disabled_is_free():
    limiter = RateLimiter(requests_per_minute=0)
    started = time.monotonic()
    for _ in range(50):
        limiter.wait()
    assert time.monotonic() - started < 0.1


def test_gemini_is_the_default_provider():
    import os

    saved = os.environ.pop("ATS_PROVIDER", None)
    try:
        settings = Settings()
        assert settings.provider == "gemini"
        assert settings.model == DEFAULT_MODELS["gemini"]
        assert settings.max_workers == 2, "free tier is rate limited; keep workers low"
    finally:
        if saved is not None:
            os.environ["ATS_PROVIDER"] = saved


def test_unknown_provider_is_reported_clearly():
    from ats.classifier import classify
    from ats.extract import extract

    settings = Settings()
    settings.provider = "not-a-provider"
    doc = extract(ROOT / "tests" / "fixtures" / "sample_human_cv.pdf")
    try:
        classify(doc, settings)
    except FatalScreeningError as exc:
        assert "gemini" in str(exc) and "claude" in str(exc)
    else:
        raise AssertionError("expected a FatalScreeningError")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'FAILED' if failures else 'ALL PASSED'} ({failures} failure(s))")
    raise SystemExit(1 if failures else 0)

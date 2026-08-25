"""Offline check of the Claude request we build, using a mock HTTP transport.

Verifies that `ats.classifier.classify` produces a request the SDK accepts (correct
parameter names, cached system prompt, adaptive thinking, JSON-schema output format)
and that the parsed verdict comes back as a `Verdict`. It does NOT hit the network.

Run: python tests/test_request_shape.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import anthropic  # noqa: E402

from ats.config import Settings  # noqa: E402
from ats.extract import extract  # noqa: E402
from ats.providers import get_provider  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"

CAPTURED: dict = {}

VERDICT_JSON = {
    "document_type": "cv_resume",
    "is_cv": True,
    "candidate_name": "Mariam A. Fathy",
    "email": "mariam.fathy.dev@example.com",
    "phone": "+20 100 555 0142",
    "role_family": "Data Scientist",
    "custom_role_title": "",
    "specialization": "Applied ML and data analysis",
    "major": "Data Science and AI",
    "seniority": "Student",
    "years_experience": 0.0,
    "top_skills": ["Python", "SQL", "Pandas", "Scikit-learn", "Spark"],
    "role_confidence": 88,
    "ai_generated_score": 18,
    "ai_signals": [],
    "human_signals": ["Named coursework and specific local employers"],
    "format_score": 90,
    "format_notes": "Standard reverse-chronological structure.",
    "quality_score": 78,
    "suggested_reject_reason": "none",
    "reasoning": "Genuine student CV with concrete, checkable detail.",
}


def handler(request: httpx2.Request) -> httpx2.Response:
    CAPTURED["url"] = str(request.url)
    CAPTURED["body"] = json.loads(request.content)
    return httpx2.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": json.dumps(VERDICT_JSON)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 2000, "output_tokens": 400},
        },
    )


def main() -> int:
    os.environ["ATS_PROVIDER"] = "claude"
    provider = get_provider("claude")
    provider._client = anthropic.Anthropic(
        api_key="sk-ant-test-not-a-real-key",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    # The mock transport cannot negotiate the fallback beta; exercise the plain path.
    provider._use_fallbacks = False

    settings = Settings()
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    verdict = provider.screen(doc, settings)

    body = CAPTURED["body"]
    checks = [
        ("model is opus-5", body["model"] == "claude-opus-5"),
        ("adaptive thinking", body["thinking"] == {"type": "adaptive"}),
        ("effort set", body["output_config"]["effort"] == "medium"),
        (
            "json_schema output format",
            body["output_config"]["format"]["type"] == "json_schema",
        ),
        (
            "role enum reached the schema",
            "Data Scientist"
            in json.dumps(body["output_config"]["format"]),
        ),
        (
            "system prompt is cached",
            body["system"][0]["cache_control"] == {"type": "ephemeral"},
        ),
        (
            "CV text is in the user message",
            "MARIAM" in body["messages"][0]["content"][0]["text"].upper(),
        ),
        (
            "file metadata is framed as weak evidence",
            "<file_metadata_notes>" in body["messages"][0]["content"][0]["text"],
        ),
        ("verdict parsed", verdict.role_family == "Data Scientist"),
        ("scores parsed", verdict.ai_generated_score == 18),
    ]

    failures = 0
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        failures += not ok

    print(f"\n{'FAILED' if failures else 'ALL PASSED'} ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

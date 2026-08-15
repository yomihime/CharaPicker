from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from core.extraction_ai import (
    FormalExtractionJsonError,
    FormalExtractionOutputTruncatedError,
    ModelTextRefusalError,
    call_formal_json_model,
)
from core.failure_classification import (
    ContentRequiresManualReviewError,
    UserOverrideRegressionError,
    classify_failure,
)
from utils.ai_model_middleware import (
    ModelCallError,
    ModelCallRequest,
    ModelCallResult,
    ModelMessage,
    _extract_message_content,
    _provider_failure_category,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "refusal_classification_cases.json"


class FailureClassificationTests(unittest.TestCase):
    def test_synthetic_failure_categories_match_prompt_tuning_boundaries(self) -> None:
        cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        for case in cases:
            with self.subTest(case=case["name"]):
                classification = classify_failure(_exception_from_case(case))
                self.assertEqual(classification.category.value, case["expected_category"])
                self.assertEqual(
                    classification.prompt_tuning_candidate,
                    case["prompt_tuning_candidate"],
                )
                self.assertEqual(
                    classification.requires_manual_review,
                    case["requires_manual_review"],
                )

    def test_provider_policy_signals_do_not_absorb_rate_limits_or_capability_errors(self) -> None:
        self.assertEqual(
            _provider_failure_category(
                status_code=400,
                provider_code="content_filter",
                message="Synthetic policy block",
            ),
            "provider_policy_refusal",
        )
        self.assertEqual(
            _provider_failure_category(
                status_code=429,
                provider_code="rate_limit_exceeded",
                message="Synthetic rate limit",
            ),
            "transport_or_auth_failure",
        )
        self.assertEqual(
            _provider_failure_category(
                status_code=400,
                provider_code="invalid_request",
                message="Audio input is not supported",
            ),
            "unsupported_capability",
        )

    def test_explicit_response_refusal_uses_model_text_category(self) -> None:
        with self.assertRaises(ModelCallError) as context:
            _extract_message_content(
                {
                    "choices": [
                        {"message": {"refusal": "Synthetic refusal", "content": None}}
                    ]
                }
            )

        self.assertEqual(context.exception.failure_category, "model_text_refusal")

    def test_plain_text_refusal_stops_json_retries(self) -> None:
        calls = 0

        def fake_call(_request: ModelCallRequest) -> ModelCallResult:
            nonlocal calls
            calls += 1
            return ModelCallResult(content="I cannot assist with that request.")

        with self.assertRaises(ModelTextRefusalError):
            call_formal_json_model(_request(), call_model=fake_call, max_attempts=3)

        self.assertEqual(calls, 1)

    def test_valid_json_with_refusal_words_remains_valid_extraction_output(self) -> None:
        content = json.dumps({"facts": ["A quoted line says I cannot assist with that."]})

        result = call_formal_json_model(
            _request(),
            call_model=lambda _request: ModelCallResult(content=content),
        )

        self.assertEqual(result.payload["facts"], ["A quoted line says I cannot assist with that."])


def _exception_from_case(case: dict[str, Any]) -> Exception:
    exception_type = case["exception_type"]
    message = case["message"]
    if exception_type == "model_call":
        return ModelCallError(
            message,
            failure_category=case.get("middleware_category", ""),
        )
    if exception_type == "model_text_refusal":
        return ModelTextRefusalError(message)
    if exception_type == "output_truncated":
        return FormalExtractionOutputTruncatedError(message)
    if exception_type == "json_parse":
        return FormalExtractionJsonError(message)
    if exception_type == "user_override":
        return UserOverrideRegressionError(message)
    if exception_type == "manual_review":
        return ContentRequiresManualReviewError(message)
    raise AssertionError(f"Unknown synthetic exception type: {exception_type}")


def _request() -> ModelCallRequest:
    return ModelCallRequest(
        purpose="synthetic_failure_classification",
        backend="openai_compatible",
        model_name="synthetic-model",
        messages=[ModelMessage(role="user", content="Return synthetic JSON")],
    )


if __name__ == "__main__":
    unittest.main()

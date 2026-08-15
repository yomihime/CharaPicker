from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.extraction_ai import (
    FormalExtractionJsonError,
    FormalExtractionOutputTruncatedError,
    ModelTextRefusalError,
)
from utils.ai_model_middleware import ModelCallError
from utils.audio_transcription import AudioTranscriptionError


class FailureCategory(str, Enum):
    PROVIDER_POLICY_REFUSAL = "provider_policy_refusal"
    MODEL_TEXT_REFUSAL = "model_text_refusal"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    OUTPUT_TRUNCATED = "output_truncated"
    JSON_PARSE_FAILURE = "json_parse_failure"
    TRANSPORT_OR_AUTH_FAILURE = "transport_or_auth_failure"
    USER_OVERRIDE_REGRESSION = "user_override_regression"
    CONTENT_REQUIRES_MANUAL_REVIEW = "content_requires_manual_review"
    LOCAL_PROCESSING_FAILURE = "local_processing_failure"
    UNKNOWN_FAILURE = "unknown_failure"


@dataclass(frozen=True, slots=True)
class FailureClassification:
    category: FailureCategory
    reason_code: str
    prompt_tuning_candidate: bool = False
    requires_manual_review: bool = False


class UserOverrideRegressionError(ValueError):
    pass


class ContentRequiresManualReviewError(ValueError):
    pass


def classify_failure(exc: Exception) -> FailureClassification:
    if isinstance(exc, ModelTextRefusalError):
        return _classification(FailureCategory.MODEL_TEXT_REFUSAL, "model_text_marker")
    if isinstance(exc, FormalExtractionOutputTruncatedError):
        return _classification(FailureCategory.OUTPUT_TRUNCATED, "output_limit_finish_reason")
    if isinstance(exc, FormalExtractionJsonError):
        return _classification(FailureCategory.JSON_PARSE_FAILURE, "formal_json_parse_error")
    if isinstance(exc, UserOverrideRegressionError):
        return _classification(FailureCategory.USER_OVERRIDE_REGRESSION, "explicit_override_error")
    if isinstance(exc, ContentRequiresManualReviewError):
        return _classification(
            FailureCategory.CONTENT_REQUIRES_MANUAL_REVIEW,
            "explicit_manual_review",
        )
    if isinstance(exc, ModelCallError):
        structured = _structured_model_category(exc.failure_category)
        if structured is not None:
            return _classification(structured, "middleware_category")
        if _legacy_policy_refusal(str(exc)):
            return _classification(FailureCategory.PROVIDER_POLICY_REFUSAL, "legacy_policy_marker")
        return _classification(FailureCategory.TRANSPORT_OR_AUTH_FAILURE, "model_call_error")
    if isinstance(exc, AudioTranscriptionError):
        return _classification(FailureCategory.LOCAL_PROCESSING_FAILURE, "audio_transcription_error")
    if isinstance(exc, (OSError, ValueError)):
        return _classification(FailureCategory.LOCAL_PROCESSING_FAILURE, "local_processing_error")
    return _classification(FailureCategory.UNKNOWN_FAILURE, "unclassified_exception")


def _classification(category: FailureCategory, reason_code: str) -> FailureClassification:
    tuning_candidate = category in {
        FailureCategory.PROVIDER_POLICY_REFUSAL,
        FailureCategory.MODEL_TEXT_REFUSAL,
    }
    return FailureClassification(
        category=category,
        reason_code=reason_code,
        prompt_tuning_candidate=tuning_candidate,
        requires_manual_review=tuning_candidate
        or category == FailureCategory.CONTENT_REQUIRES_MANUAL_REVIEW,
    )


def _structured_model_category(value: str) -> FailureCategory | None:
    try:
        return FailureCategory(value)
    except ValueError:
        return None


def _legacy_policy_refusal(message: str) -> bool:
    text = message.casefold()
    return any(
        marker in text
        for marker in (
            "content safety",
            "data inspection",
            "datainspectionfailed",
            "inappropriate content",
        )
    )

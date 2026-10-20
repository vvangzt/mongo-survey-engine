"""Typed, machine-readable errors for the validation/jump engine."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    REQUIRED = "required"
    MALFORMED_ANSWER = "malformed_answer"
    QUESTION_MISMATCH = "question_mismatch"
    TYPE_MISMATCH = "type_mismatch"
    UNKNOWN_OPTION = "unknown_option"
    SELECTION_COUNT = "selection_count"
    EMPTY_TEXT = "empty_text"
    TEXT_TOO_SHORT = "text_too_short"
    TEXT_TOO_LONG = "text_too_long"
    NUMBER_NOT_INTEGER = "number_not_integer"
    NUMBER_OUT_OF_RANGE = "number_out_of_range"
    UNSUPPORTED_OPERATOR = "unsupported_operator"
    OPERATOR_TYPE_MISMATCH = "operator_type_mismatch"
    INVALID_OPERAND = "invalid_operand"
    ANSWER_CONTEXT_MISSING = "answer_context_missing"
    INVALID_JUMP_TARGET = "invalid_jump_target"
    INVALID_CONDITION_GROUP = "invalid_condition_group"


class EngineError(ValueError):
    """Base class for all domain errors raised by the engine."""


class SubmissionValidationError(EngineError):
    """Base class for validation/evaluation errors.

    Keeping a common base makes it easy for the HTTP layer to map these errors
    to a 400/422 response without catching arbitrary exceptions.
    """

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | str | None = None,
        question_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code.value if isinstance(code, ErrorCode) else code
        self.question_id = question_id
        self.details = details or {}


class AnswerValidationError(SubmissionValidationError):
    """An answer is structurally valid but violates the question's rules."""


class JumpEvaluationError(SubmissionValidationError):
    """A stored jump rule cannot be evaluated safely."""


class SurveyEnded(EngineError):
    """Control-flow exception for the convenience next-question function.

    The full-path evaluator uses ``JumpDecision`` instead. This exception only
    disambiguates ``end`` from ``next`` in the two-argument convenience API.
    """


__all__ = [
    "AnswerValidationError",
    "EngineError",
    "ErrorCode",
    "JumpEvaluationError",
    "SubmissionValidationError",
    "SurveyEnded",
]

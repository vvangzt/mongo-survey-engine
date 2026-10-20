"""Executable Pydantic contract, validation layer and jump-logic engine."""

from .engine import (
    AdvanceResult,
    SubmissionResult,
    advance_survey,
    validate_response,
    validate_submission,
)
from .errors import (
    AnswerValidationError,
    EngineError,
    ErrorCode,
    JumpEvaluationError,
    SubmissionValidationError,
    SurveyEnded,
)
from .jump import (
    DEFAULT_OPERATOR_REGISTRY,
    JumpDecision,
    OperatorRegistry,
    OperatorSpec,
    evaluate_condition,
    evaluate_condition_group,
    evaluate_jump,
    evaluate_next_question,
    evaluate_operator,
    register_default_operators,
)
from .models import *  # noqa: F401,F403
from .models import __all__ as _model_exports
from .validation import validate_answer

__all__ = [
    *_model_exports,
    "AdvanceResult",
    "AnswerValidationError",
    "DEFAULT_OPERATOR_REGISTRY",
    "EngineError",
    "ErrorCode",
    "JumpDecision",
    "JumpEvaluationError",
    "OperatorRegistry",
    "OperatorSpec",
    "SubmissionResult",
    "SubmissionValidationError",
    "SurveyEnded",
    "advance_survey",
    "evaluate_condition",
    "evaluate_condition_group",
    "evaluate_jump",
    "evaluate_next_question",
    "evaluate_operator",
    "register_default_operators",
    "validate_answer",
    "validate_response",
    "validate_submission",
]

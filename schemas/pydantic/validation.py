"""Pure answer-validation functions.

Every function is independent of MongoDB, HTTP and FastAPI. Callers can test
the rules directly and reuse the same code for per-question UI validation and
whole-page submission validation.
"""

from __future__ import annotations

import math

from .errors import AnswerValidationError, ErrorCode
from .models import (
    Answer,
    MultiChoiceAnswer,
    MultiChoiceQuestion,
    NumberAnswer,
    NumberQuestion,
    Question,
    SAFE_INT_MAX,
    SAFE_INT_MIN,
    SingleChoiceAnswer,
    SingleChoiceQuestion,
    TextAnswer,
    TextQuestion,
)


def validate_answer(
    question: Question,
    answer: Answer | None,
    *,
    required: bool | None = None,
) -> Answer | None:
    """Validate one answer and return its normalized form.

    Returns ``None`` for an omitted optional answer. Raises
    ``AnswerValidationError`` with a stable ``code`` for every rule violation.
    The input is never mutated; trimmed text is returned as a model copy.

    ``required`` may override ``question.required`` for a computed display path,
    but defaults to the question's own flag.
    """

    is_required = question.required if required is None else required
    if answer is None:
        if is_required:
            raise AnswerValidationError(
                f"required question was not answered: {question.question_id}",
                code=ErrorCode.REQUIRED,
                question_id=question.question_id,
            )
        return None

    if not isinstance(
        answer,
        (SingleChoiceAnswer, MultiChoiceAnswer, TextAnswer, NumberAnswer),
    ):
        raise AnswerValidationError(
            f"unsupported answer object for {question.question_id}",
            code=ErrorCode.MALFORMED_ANSWER,
            question_id=question.question_id,
        )

    if answer.question_id != question.question_id:
        raise AnswerValidationError(
            "answer.question_id does not match the question",
            code=ErrorCode.QUESTION_MISMATCH,
            question_id=question.question_id,
            details={
                "expected": question.question_id,
                "actual": answer.question_id,
            },
        )

    if answer.type != question.type:
        raise AnswerValidationError(
            f"answer type {answer.type!r} does not match question type "
            f"{question.type!r}",
            code=ErrorCode.TYPE_MISMATCH,
            question_id=question.question_id,
            details={"expected": question.type, "actual": answer.type},
        )

    if isinstance(question, SingleChoiceQuestion) and isinstance(
        answer, SingleChoiceAnswer
    ):
        return _validate_single_choice(question, answer)

    if isinstance(question, MultiChoiceQuestion) and isinstance(
        answer, MultiChoiceAnswer
    ):
        return _validate_multi_choice(question, answer, is_required=is_required)

    if isinstance(question, TextQuestion) and isinstance(answer, TextAnswer):
        return _validate_text(question, answer)

    if isinstance(question, NumberQuestion) and isinstance(answer, NumberAnswer):
        return _validate_number(question, answer)

    raise AnswerValidationError(
        f"unsupported answer/question pair for {question.question_id}",
        code=ErrorCode.MALFORMED_ANSWER,
        question_id=question.question_id,
    )


def _validate_single_choice(
    question: SingleChoiceQuestion, answer: SingleChoiceAnswer
) -> SingleChoiceAnswer:
    if len(answer.option_ids) != 1:
        raise AnswerValidationError(
            "single-choice answers require exactly one option_id",
            code=ErrorCode.SELECTION_COUNT,
            question_id=question.question_id,
            details={"count": len(answer.option_ids), "expected": 1},
        )
    option_id = answer.option_ids[0]
    valid_ids = {option.option_id for option in question.options}
    if option_id not in valid_ids:
        raise AnswerValidationError(
            f"option {option_id!r} does not belong to {question.question_id}",
            code=ErrorCode.UNKNOWN_OPTION,
            question_id=question.question_id,
            details={"option_id": option_id},
        )
    return answer


def _validate_multi_choice(
    question: MultiChoiceQuestion,
    answer: MultiChoiceAnswer,
    *,
    is_required: bool,
) -> MultiChoiceAnswer:
    selected = answer.option_ids
    if len(set(selected)) != len(selected):
        raise AnswerValidationError(
            "multi-choice answers must not contain duplicate option_ids",
            code=ErrorCode.MALFORMED_ANSWER,
            question_id=question.question_id,
            details={"option_ids": selected},
        )

    valid_ids = {option.option_id for option in question.options}
    unknown = [option_id for option_id in selected if option_id not in valid_ids]
    if unknown:
        raise AnswerValidationError(
            f"unknown option(s) for {question.question_id}: {unknown}",
            code=ErrorCode.UNKNOWN_OPTION,
            question_id=question.question_id,
            details={"option_ids": unknown},
        )

    count = len(selected)
    rules = question.validation
    if rules.exact_selected is not None:
        minimum = maximum = rules.exact_selected
        mode = "exact"
    else:
        minimum = (
            rules.min_selected
            if rules.min_selected is not None
            else (1 if is_required else 0)
        )
        maximum = (
            rules.max_selected
            if rules.max_selected is not None
            else len(question.options)
        )
        mode = "range"

    if not minimum <= count <= maximum:
        if mode == "exact":
            message = (
                f"{question.question_id} requires exactly {minimum} selected "
                f"options, got {count}"
            )
        else:
            message = (
                f"{question.question_id} requires {minimum}..{maximum} selected "
                f"options, got {count}"
            )
        raise AnswerValidationError(
            message,
            code=ErrorCode.SELECTION_COUNT,
            question_id=question.question_id,
            details={
                "actual": count,
                "min": minimum,
                "max": maximum,
                "mode": mode,
            },
        )
    return answer


def _validate_text(
    question: TextQuestion, answer: TextAnswer
) -> TextAnswer:
    rules = question.validation
    normalized = answer.text.strip() if rules.trim else answer.text

    if not normalized:
        raise AnswerValidationError(
            f"text answer for {question.question_id} is empty",
            code=ErrorCode.EMPTY_TEXT,
            question_id=question.question_id,
        )

    # Python len counts Unicode code points, matching the documented contract.
    length = len(normalized)
    if length < rules.min_length:
        raise AnswerValidationError(
            f"text answer for {question.question_id} is too short",
            code=ErrorCode.TEXT_TOO_SHORT,
            question_id=question.question_id,
            details={
                "length": length,
                "min_length": rules.min_length,
                "max_length": rules.max_length,
            },
        )
    if length > rules.max_length:
        raise AnswerValidationError(
            f"text answer for {question.question_id} is too long",
            code=ErrorCode.TEXT_TOO_LONG,
            question_id=question.question_id,
            details={
                "length": length,
                "min_length": rules.min_length,
                "max_length": rules.max_length,
            },
        )

    if normalized == answer.text:
        return answer
    return answer.model_copy(update={"text": normalized})


def _validate_number(
    question: NumberQuestion, answer: NumberAnswer
) -> NumberAnswer:
    value = answer.number

    # Pydantic normally guarantees this, but the engine is also used with
    # defensively constructed/tested objects.
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise AnswerValidationError(
            f"answer for {question.question_id} must be a finite number",
            code=ErrorCode.MALFORMED_ANSWER,
            question_id=question.question_id,
            details={"value": value},
        )

    rules = question.validation
    if rules.integer:
        if not isinstance(value, int):
            raise AnswerValidationError(
                f"answer for {question.question_id} must be an integer",
                code=ErrorCode.NUMBER_NOT_INTEGER,
                question_id=question.question_id,
                details={"value": value},
            )
        if not SAFE_INT_MIN <= value <= SAFE_INT_MAX:
            raise AnswerValidationError(
                f"answer for {question.question_id} exceeds the safe integer range",
                code=ErrorCode.NUMBER_OUT_OF_RANGE,
                question_id=question.question_id,
                details={
                    "value": value,
                    "safe_min": SAFE_INT_MIN,
                    "safe_max": SAFE_INT_MAX,
                },
            )

    if rules.min is not None and value < rules.min:
        raise AnswerValidationError(
            f"answer for {question.question_id} is below the minimum",
            code=ErrorCode.NUMBER_OUT_OF_RANGE,
            question_id=question.question_id,
            details={"value": value, "min": rules.min, "max": rules.max},
        )
    if rules.max is not None and value > rules.max:
        raise AnswerValidationError(
            f"answer for {question.question_id} is above the maximum",
            code=ErrorCode.NUMBER_OUT_OF_RANGE,
            question_id=question.question_id,
            details={"value": value, "min": rules.min, "max": rules.max},
        )
    return answer


__all__ = ["validate_answer"]

"""Pure jump-rule evaluation with a pluggable operator registry.

The persisted rule stays in ``question.logic.rules`` (``QuestionBase.jump_rules``
is a read-only convenience property). Rules are evaluated in order; the first
matching rule wins. This module never reads the database or the clock, which
makes every function deterministic and easy to unit test.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .errors import ErrorCode, JumpEvaluationError, SurveyEnded
from .models import (
    Answer,
    ConditionGroup,
    ConditionMode,
    EndAction,
    GotoAction,
    JumpCondition,
    MultiChoiceAnswer,
    NumberAnswer,
    Question,
    SAFE_INT_MAX,
    SAFE_INT_MIN,
    SingleChoiceAnswer,
    TextAnswer,
)

ANSWER_TYPES = frozenset(
    {"single_choice", "multi_choice", "text", "number"}
)
OPTION_ID_RE = re.compile(r"^o_[A-Za-z0-9_-]{8,64}$")

OperatorHandler = Callable[[Answer, object], bool]


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    name: str
    answer_types: frozenset[str]
    handler: OperatorHandler


class OperatorRegistry:
    """Registry-based operator dispatch.

    New operators do not require editing a growing if/elif chain. A plugin can
    be added at process startup:

        registry = OperatorRegistry.with_default_operators()

        @registry.register("contains", answer_types={"text"})
        def contains(answer, operand):
            return isinstance(operand, str) and operand in answer.text

    The canonical v1 schema still has a closed operator enum, so a persisted
    operator is added together with a new content-schema version. The evaluator
    extension point itself is independent of that storage change.
    """

    def __init__(self) -> None:
        self._specs: dict[str, OperatorSpec] = {}

    @classmethod
    def with_default_operators(cls) -> "OperatorRegistry":
        registry = cls()
        register_default_operators(registry)
        return registry

    def register(
        self,
        name: str,
        *,
        answer_types: Collection[str],
        replace: bool = False,
    ) -> Callable[[OperatorHandler], OperatorHandler]:
        if not name or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError(f"invalid operator name: {name!r}")
        normalized_types = frozenset(answer_types)
        if not normalized_types:
            raise ValueError("at least one supported answer type is required")
        unknown_types = normalized_types - ANSWER_TYPES
        if unknown_types:
            raise ValueError(f"unknown answer types: {sorted(unknown_types)}")

        def decorator(handler: OperatorHandler) -> OperatorHandler:
            if not callable(handler):
                raise TypeError("operator handler must be callable")
            if name in self._specs and not replace:
                raise ValueError(f"operator already registered: {name}")
            self._specs[name] = OperatorSpec(
                name=name,
                answer_types=normalized_types,
                handler=handler,
            )
            return handler

        return decorator

    def has(self, name: str) -> bool:
        return name in self._specs

    def evaluate(self, name: str, operand: object, answer: Answer) -> bool:
        if not isinstance(
            answer,
            (SingleChoiceAnswer, MultiChoiceAnswer, TextAnswer, NumberAnswer),
        ):
            raise JumpEvaluationError(
                "unsupported answer object passed to operator evaluation",
                code=ErrorCode.MALFORMED_ANSWER,
            )

        spec = self._specs.get(name)
        if spec is None:
            raise JumpEvaluationError(
                f"unsupported jump operator: {name!r}",
                code=ErrorCode.UNSUPPORTED_OPERATOR,
                question_id=answer.question_id,
                details={"operator": name},
            )
        if answer.type not in spec.answer_types:
            raise JumpEvaluationError(
                f"operator {name!r} does not support answer type {answer.type!r}",
                code=ErrorCode.OPERATOR_TYPE_MISMATCH,
                question_id=answer.question_id,
                details={
                    "operator": name,
                    "answer_type": answer.type,
                    "allowed": sorted(spec.answer_types),
                },
            )
        try:
            result = spec.handler(answer, operand)
        except JumpEvaluationError:
            raise
        except Exception as exc:  # defensive boundary around plugins
            raise JumpEvaluationError(
                f"operator {name!r} failed: {exc}",
                code=ErrorCode.INVALID_OPERAND,
                question_id=answer.question_id,
                details={"operator": name, "operand": operand},
            ) from exc
        if type(result) is not bool:
            raise JumpEvaluationError(
                f"operator {name!r} returned {type(result).__name__}, expected bool",
                code=ErrorCode.INVALID_OPERAND,
                question_id=answer.question_id,
                details={"operator": name},
            )
        return result


def _bad_operand(operator: str, operand: object, expected: str) -> JumpEvaluationError:
    return JumpEvaluationError(
        f"operator {operator!r} requires {expected}",
        code=ErrorCode.INVALID_OPERAND,
        details={"operator": operator, "operand": operand, "expected": expected},
    )


def _require_integer(operator: str, operand: object) -> int:
    if isinstance(operand, bool) or not isinstance(operand, int):
        raise _bad_operand(operator, operand, "a safe integer")
    if not SAFE_INT_MIN <= operand <= SAFE_INT_MAX:
        raise _bad_operand(operator, operand, "a safe integer")
    return operand


def _require_number(operator: str, operand: object) -> float | int:
    if (
        isinstance(operand, bool)
        or not isinstance(operand, (int, float))
        or not math.isfinite(float(operand))
    ):
        raise _bad_operand(operator, operand, "a finite number")
    return operand


def _require_option_id(operator: str, operand: object) -> str:
    if not isinstance(operand, str) or not OPTION_ID_RE.fullmatch(operand):
        raise _bad_operand(operator, operand, "one valid option_id")
    return operand


def _require_option_ids(operator: str, operand: object) -> tuple[str, ...]:
    if (
        isinstance(operand, (str, bytes))
        or not isinstance(operand, Sequence)
        or not operand
    ):
        raise _bad_operand(operator, operand, "a non-empty option_id array")
    values = tuple(operand)
    if any(
        not isinstance(item, str) or not OPTION_ID_RE.fullmatch(item)
        for item in values
    ):
        raise _bad_operand(operator, operand, "a non-empty option_id array")
    if len(set(values)) != len(values):
        raise _bad_operand(operator, operand, "a unique option_id array")
    return values


def _require_range(operator: str, operand: object) -> tuple[float | int, float | int]:
    if (
        isinstance(operand, (str, bytes))
        or not isinstance(operand, Sequence)
        or len(operand) != 2
    ):
        raise _bad_operand(operator, operand, "an ordered [low, high] pair")
    low = _require_number(operator, operand[0])
    high = _require_number(operator, operand[1])
    if low > high:
        raise _bad_operand(operator, operand, "an ordered [low, high] pair")
    return low, high


def _single_answer_value(answer: SingleChoiceAnswer) -> str:
    if len(answer.option_ids) != 1:
        raise JumpEvaluationError(
            "single-choice answer does not contain exactly one option_id",
            code=ErrorCode.MALFORMED_ANSWER,
            question_id=answer.question_id,
        )
    return answer.option_ids[0]


def _multi_answer_values(answer: MultiChoiceAnswer) -> set[str]:
    return set(answer.option_ids)


def _answer_number(answer: NumberAnswer) -> float | int:
    value = answer.number
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise JumpEvaluationError(
            "number answer is not a finite number",
            code=ErrorCode.MALFORMED_ANSWER,
            question_id=answer.question_id,
        )
    return value


def _eq(answer: Answer, operand: object) -> bool:
    if isinstance(answer, SingleChoiceAnswer):
        return _single_answer_value(answer) == _require_option_id("eq", operand)
    if isinstance(answer, NumberAnswer):
        return _answer_number(answer) == _require_number("eq", operand)
    raise AssertionError("registry allowed an unsupported eq answer type")


def _neq(answer: Answer, operand: object) -> bool:
    return not _eq(answer, operand)


def _in(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, SingleChoiceAnswer)
    return _single_answer_value(answer) in _require_option_ids("in", operand)


def _not_in(answer: Answer, operand: object) -> bool:
    return not _in(answer, operand)


def _includes_any(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, MultiChoiceAnswer)
    return bool(_multi_answer_values(answer) & set(_require_option_ids("includes_any", operand)))


def _includes_all(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, MultiChoiceAnswer)
    return set(_require_option_ids("includes_all", operand)).issubset(
        _multi_answer_values(answer)
    )


def _includes_none(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, MultiChoiceAnswer)
    return not (
        _multi_answer_values(answer)
        & set(_require_option_ids("includes_none", operand))
    )


def _equals_set(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, MultiChoiceAnswer)
    return _multi_answer_values(answer) == set(
        _require_option_ids("equals_set", operand)
    )


def _selection_count_eq(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, MultiChoiceAnswer)
    return len(_multi_answer_values(answer)) == _require_integer(
        "selection_count_eq", operand
    )


def _selection_count_gte(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, MultiChoiceAnswer)
    return len(_multi_answer_values(answer)) >= _require_integer(
        "selection_count_gte", operand
    )


def _selection_count_lte(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, MultiChoiceAnswer)
    return len(_multi_answer_values(answer)) <= _require_integer(
        "selection_count_lte", operand
    )


def _gt(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, NumberAnswer)
    return _answer_number(answer) > _require_number("gt", operand)


def _gte(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, NumberAnswer)
    return _answer_number(answer) >= _require_number("gte", operand)


def _lt(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, NumberAnswer)
    return _answer_number(answer) < _require_number("lt", operand)


def _lte(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, NumberAnswer)
    return _answer_number(answer) <= _require_number("lte", operand)


def _between(answer: Answer, operand: object) -> bool:
    assert isinstance(answer, NumberAnswer)
    low, high = _require_range("between", operand)
    return low <= _answer_number(answer) <= high


def register_default_operators(registry: OperatorRegistry) -> None:
    """Register the v1 operator set. Registration is idempotent per registry."""

    registry.register("eq", answer_types={"single_choice", "number"})(_eq)
    registry.register("neq", answer_types={"single_choice", "number"})(_neq)
    registry.register("in", answer_types={"single_choice"})(_in)
    registry.register("not_in", answer_types={"single_choice"})(_not_in)
    registry.register("includes_any", answer_types={"multi_choice"})(_includes_any)
    registry.register("includes_all", answer_types={"multi_choice"})(_includes_all)
    registry.register("includes_none", answer_types={"multi_choice"})(_includes_none)
    registry.register("equals_set", answer_types={"multi_choice"})(_equals_set)
    registry.register(
        "selection_count_eq", answer_types={"multi_choice"}
    )(_selection_count_eq)
    registry.register(
        "selection_count_gte", answer_types={"multi_choice"}
    )(_selection_count_gte)
    registry.register(
        "selection_count_lte", answer_types={"multi_choice"}
    )(_selection_count_lte)
    registry.register("gt", answer_types={"number"})(_gt)
    registry.register("gte", answer_types={"number"})(_gte)
    registry.register("lt", answer_types={"number"})(_lt)
    registry.register("lte", answer_types={"number"})(_lte)
    registry.register("between", answer_types={"number"})(_between)


DEFAULT_OPERATOR_REGISTRY = OperatorRegistry.with_default_operators()


def evaluate_operator(
    operator: str,
    operand: object,
    answer: Answer,
    *,
    registry: OperatorRegistry | None = None,
) -> bool:
    """Evaluate one operator against one answer using the selected registry."""

    return (registry or DEFAULT_OPERATOR_REGISTRY).evaluate(
        operator, operand, answer
    )


def _source_answer(
    condition: JumpCondition,
    *,
    current_question: Question,
    user_answer: Answer | None,
    prior_answers: Mapping[str, Answer] | None,
) -> Answer | None:
    if condition.question_id == current_question.question_id:
        return user_answer

    if prior_answers is None:
        raise JumpEvaluationError(
            f"condition references earlier question {condition.question_id}; "
            "pass prior_answers to evaluate it",
            code=ErrorCode.ANSWER_CONTEXT_MISSING,
            question_id=current_question.question_id,
            details={"source_question_id": condition.question_id},
        )
    return prior_answers.get(condition.question_id)


def evaluate_condition(
    condition: JumpCondition,
    *,
    current_question: Question,
    user_answer: Answer | None,
    prior_answers: Mapping[str, Answer] | None = None,
    registry: OperatorRegistry | None = None,
) -> bool:
    """Evaluate one condition; an unanswered/non-visible source is false."""

    source = _source_answer(
        condition,
        current_question=current_question,
        user_answer=user_answer,
        prior_answers=prior_answers,
    )
    if source is None:
        return False
    if source.question_id != condition.question_id:
        raise JumpEvaluationError(
            "prior_answers contains an answer under the wrong question_id",
            code=ErrorCode.QUESTION_MISMATCH,
            question_id=condition.question_id,
            details={
                "condition_question_id": condition.question_id,
                "answer_question_id": source.question_id,
            },
        )
    return evaluate_operator(
        condition.operator.value,
        condition.value,
        source,
        registry=registry,
    )


def evaluate_condition_group(
    group: ConditionGroup,
    *,
    current_question: Question,
    user_answer: Answer | None,
    prior_answers: Mapping[str, Answer] | None = None,
    registry: OperatorRegistry | None = None,
) -> bool:
    """Evaluate an all/any group with short-circuiting."""

    if not group.conditions:
        raise JumpEvaluationError(
            "condition group must contain at least one condition",
            code=ErrorCode.INVALID_CONDITION_GROUP,
            question_id=current_question.question_id,
        )

    results = (
        evaluate_condition(
            condition,
            current_question=current_question,
            user_answer=user_answer,
            prior_answers=prior_answers,
            registry=registry,
        )
        for condition in group.conditions
    )
    if group.mode is ConditionMode.all:
        return all(results)
    return any(results)


@dataclass(frozen=True, slots=True)
class JumpDecision:
    """Explicit result of evaluating a question's jump rules."""

    action: Literal["goto", "next", "end"]
    target_question_id: str | None = None
    matched_rule_id: str | None = None

    def __post_init__(self) -> None:
        if self.action == "goto":
            if not self.target_question_id:
                raise ValueError("a goto decision requires target_question_id")
        elif self.target_question_id is not None:
            raise ValueError("next/end decisions must not carry a target_question_id")


def evaluate_jump(
    current_question: Question,
    user_answer: Answer | None,
    *,
    prior_answers: Mapping[str, Answer] | None = None,
    registry: OperatorRegistry | None = None,
) -> JumpDecision:
    """Evaluate rules in order and return an unambiguous decision.

    - First matching rule wins.
    - No match uses the persisted fallback (next/end).
    - A missing current or prior answer is treated as "condition is false";
      a missing *context* for a rule that references an earlier question raises
      ``JumpEvaluationError`` rather than silently taking the wrong branch.
    """

    if user_answer is not None and (
        user_answer.question_id != current_question.question_id
    ):
        raise JumpEvaluationError(
            "user_answer belongs to a different question",
            code=ErrorCode.QUESTION_MISMATCH,
            question_id=current_question.question_id,
            details={"answer_question_id": user_answer.question_id},
        )

    logic = current_question.logic
    if logic is None:
        return JumpDecision(action="next")

    for rule in logic.rules:
        if not evaluate_condition_group(
            rule.when,
            current_question=current_question,
            user_answer=user_answer,
            prior_answers=prior_answers,
            registry=registry,
        ):
            continue

        if isinstance(rule.then, GotoAction):
            return JumpDecision(
                action="goto",
                target_question_id=rule.then.target_question_id,
                matched_rule_id=rule.rule_id,
            )
        if isinstance(rule.then, EndAction):
            return JumpDecision(action="end", matched_rule_id=rule.rule_id)
        raise JumpEvaluationError(
            f"unsupported jump action in rule {rule.rule_id}",
            code=ErrorCode.INVALID_JUMP_TARGET,
            question_id=current_question.question_id,
            details={"rule_id": rule.rule_id},
        )

    if logic.fallback.action == "end":
        return JumpDecision(action="end")
    return JumpDecision(action="next")


def evaluate_next_question(
    current_question: Question,
    user_answer: Answer | None,
    *,
    prior_answers: Mapping[str, Answer] | None = None,
    registry: OperatorRegistry | None = None,
) -> str | None:
    """Return an explicit goto target, or ``None`` for natural/next flow.

    This is the requested convenience API. Because a bare ``None`` cannot
    distinguish "go to the next sequential question" from "end the survey",
    an explicit end raises ``SurveyEnded`` instead of being silently mistaken
    for sequential flow. For orchestration code, prefer ``evaluate_jump``:
    its ``JumpDecision`` makes all three outcomes explicit.
    """

    decision = evaluate_jump(
        current_question,
        user_answer,
        prior_answers=prior_answers,
        registry=registry,
    )
    if decision.action == "goto":
        return decision.target_question_id
    if decision.action == "end":
        raise SurveyEnded(
            f"survey ends after {current_question.question_id}"
        )
    return None


__all__ = [
    "DEFAULT_OPERATOR_REGISTRY",
    "JumpDecision",
    "OperatorRegistry",
    "OperatorSpec",
    "evaluate_condition",
    "evaluate_condition_group",
    "evaluate_jump",
    "evaluate_next_question",
    "evaluate_operator",
    "register_default_operators",
]

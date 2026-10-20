"""Unit tests for the pure validation and jump-evaluation layers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schemas.pydantic import (  # noqa: E402
    AnswerValidationError,
    ConditionGroup,
    ConditionMode,
    ConditionOperator,
    EndAction,
    ErrorCode,
    FallbackAction,
    GotoAction,
    JumpCondition,
    JumpEvaluationError,
    JumpLogic,
    JumpRule,
    MultiChoiceAnswer,
    MultiChoiceQuestion,
    MultiChoiceValidation,
    NumberAnswer,
    NumberQuestion,
    NumberValidation,
    OperatorRegistry,
    Option,
    SingleChoiceAnswer,
    SingleChoiceQuestion,
    SurveyEnded,
    TextAnswer,
    TextQuestion,
    TextValidation,
    evaluate_jump,
    evaluate_next_question,
    evaluate_operator,
    validate_answer,
)


def option(option_id: str, label: str) -> Option:
    return Option(option_id=option_id, label=label)


A = option("o_a_00000001", "A")
B = option("o_b_00000001", "B")
C = option("o_c_00000001", "C")
D = option("o_d_00000001", "D")


def single_question(
    question_id: str = "q_single_0001",
    *,
    logic: JumpLogic | None = None,
    options: list[Option] | None = None,
) -> SingleChoiceQuestion:
    return SingleChoiceQuestion(
        question_id=question_id,
        type="single_choice",
        title="单选题",
        required=False,
        options=options if options is not None else [A, B],
        logic=logic,
    )


def multi_question(
    *,
    validation: MultiChoiceValidation | None = None,
    logic: JumpLogic | None = None,
) -> MultiChoiceQuestion:
    return MultiChoiceQuestion(
        question_id="q_multi_0002",
        type="multi_choice",
        title="多选题",
        required=False,
        options=[A, B, C, D],
        validation=validation
        or MultiChoiceValidation(min_selected=2, max_selected=3),
        logic=logic,
    )


def number_question(
    *,
    minimum: int | float | None = 0,
    maximum: int | float | None = 18,
    integer: bool = True,
    logic: JumpLogic | None = None,
    question_id: str = "q_number_0003",
) -> NumberQuestion:
    return NumberQuestion(
        question_id=question_id,
        type="number",
        title="数字题",
        required=False,
        validation=NumberValidation(
            integer=integer, min=minimum, max=maximum
        ),
        logic=logic,
    )


def text_question(
    *, logic: JumpLogic | None = None, question_id: str = "q_text_0004"
) -> TextQuestion:
    return TextQuestion(
        question_id=question_id,
        type="text",
        title="文本题",
        required=False,
        validation=TextValidation(min_length=2, max_length=4, trim=True),
        logic=logic,
    )


def goto_rule(
    *,
    rule_id: str,
    source_question_id: str,
    operator: ConditionOperator,
    value: object,
    target: str,
    mode: ConditionMode = ConditionMode.all,
) -> JumpRule:
    return JumpRule(
        rule_id=rule_id,
        when=ConditionGroup(
            mode=mode,
            conditions=[
                JumpCondition(
                    question_id=source_question_id,
                    operator=operator,
                    value=value,
                )
            ],
        ),
        then=GotoAction(action="goto", target_question_id=target),
    )


def logic_with(
    rule: JumpRule | None = None,
    *,
    fallback: str = "next",
) -> JumpLogic:
    return JumpLogic(
        fallback=FallbackAction(action=fallback),
        rules=[] if rule is None else [rule],
    )


def single_answer(option_id: str, qid: str = "q_single_0001") -> SingleChoiceAnswer:
    return SingleChoiceAnswer(
        question_id=qid,
        type="single_choice",
        option_ids=[option_id],
    )


def multi_answer(
    option_ids: list[str], qid: str = "q_multi_0002"
) -> MultiChoiceAnswer:
    return MultiChoiceAnswer(
        question_id=qid,
        type="multi_choice",
        option_ids=option_ids,
    )


def number_answer(value: int, qid: str = "q_number_0003") -> NumberAnswer:
    return NumberAnswer(question_id=qid, type="number", number=value)


def text_answer(value: str, qid: str = "q_text_0004") -> TextAnswer:
    return TextAnswer(question_id=qid, type="text", text=value)


class AnswerValidationTests(unittest.TestCase):
    def test_multi_rejects_below_minimum(self) -> None:
        q = multi_question()
        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(q, multi_answer([A.option_id]))
        self.assertEqual(ctx.exception.code, ErrorCode.SELECTION_COUNT.value)
        self.assertEqual(ctx.exception.details["actual"], 1)
        self.assertEqual(ctx.exception.details["min"], 2)

    def test_multi_rejects_above_maximum(self) -> None:
        q = multi_question()
        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(
                q,
                multi_answer(
                    [A.option_id, B.option_id, C.option_id, D.option_id]
                ),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.SELECTION_COUNT.value)
        self.assertEqual(ctx.exception.details["actual"], 4)
        self.assertEqual(ctx.exception.details["max"], 3)

    def test_multi_accepts_range(self) -> None:
        q = multi_question()
        answer = multi_answer([A.option_id, B.option_id, C.option_id])
        self.assertIs(validate_answer(q, answer), answer)

    def test_multi_exact_count(self) -> None:
        q = multi_question(
            validation=MultiChoiceValidation(exact_selected=2)
        )
        self.assertIsNotNone(
            validate_answer(q, multi_answer([A.option_id, B.option_id]))
        )
        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(q, multi_answer([A.option_id]))
        self.assertEqual(ctx.exception.code, ErrorCode.SELECTION_COUNT.value)
        self.assertEqual(ctx.exception.details["mode"], "exact")

    def test_multi_unknown_option(self) -> None:
        q = multi_question(
            validation=MultiChoiceValidation(min_selected=1, max_selected=3)
        )
        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(
                q,
                multi_answer(["o_unknown_0001", B.option_id]),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.UNKNOWN_OPTION.value)

    def test_number_bounds_are_inclusive(self) -> None:
        q = number_question(minimum=18, maximum=60)
        for value in (18, 60):
            self.assertIsNotNone(validate_answer(q, number_answer(value)))
        for value in (17, 61):
            with self.assertRaises(AnswerValidationError) as ctx:
                validate_answer(q, number_answer(value))
            self.assertEqual(
                ctx.exception.code, ErrorCode.NUMBER_OUT_OF_RANGE.value
            )

    def test_number_integer_flag_and_decimal_answers(self) -> None:
        integer_q = number_question(minimum=0, maximum=100, integer=True)
        decimal_q = number_question(minimum=0, maximum=100, integer=False)

        invalid_float = NumberAnswer.model_construct(
            question_id=integer_q.question_id, type="number", number=18.5
        )
        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(integer_q, invalid_float)
        self.assertEqual(
            ctx.exception.code, ErrorCode.NUMBER_NOT_INTEGER.value
        )

        decimal = NumberAnswer(
            question_id=decimal_q.question_id,
            type="number",
            number=18.5,
        )
        self.assertIs(validate_answer(decimal_q, decimal), decimal)

        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(
                decimal_q,
                NumberAnswer(
                    question_id=decimal_q.question_id,
                    type="number",
                    number=100.5,
                ),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.NUMBER_OUT_OF_RANGE.value)

        invalid_bool = NumberAnswer.model_construct(
            question_id=integer_q.question_id, type="number", number=True
        )
        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(integer_q, invalid_bool)
        self.assertEqual(ctx.exception.code, ErrorCode.MALFORMED_ANSWER.value)

    def test_text_length_is_measured_after_trim_and_returns_normalized_copy(
        self,
    ) -> None:
        q = text_question()
        normalized = validate_answer(q, text_answer("  ab  "))
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized.text, "ab")

        with self.assertRaises(AnswerValidationError) as short:
            validate_answer(q, text_answer(" a "))
        self.assertEqual(short.exception.code, ErrorCode.TEXT_TOO_SHORT.value)

        with self.assertRaises(AnswerValidationError) as long:
            validate_answer(q, text_answer("abcde"))
        self.assertEqual(long.exception.code, ErrorCode.TEXT_TOO_LONG.value)

    def test_text_whitespace_only_is_empty(self) -> None:
        q = text_question()
        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(q, text_answer("   "))
        self.assertEqual(ctx.exception.code, ErrorCode.EMPTY_TEXT.value)

    def test_required_and_optional_missing_answers(self) -> None:
        q = single_question()
        self.assertIsNone(validate_answer(q, None))
        required = q.model_copy(update={"required": True})
        with self.assertRaises(AnswerValidationError) as ctx:
            validate_answer(required, None)
        self.assertEqual(ctx.exception.code, ErrorCode.REQUIRED.value)

    def test_question_and_type_mismatch(self) -> None:
        q = single_question()
        with self.assertRaises(AnswerValidationError) as wrong_question:
            validate_answer(q, single_answer(A.option_id, qid="q_other_0001"))
        self.assertEqual(
            wrong_question.exception.code, ErrorCode.QUESTION_MISMATCH.value
        )

        with self.assertRaises(AnswerValidationError) as wrong_type:
            validate_answer(
                q,
                NumberAnswer.model_construct(
                    question_id=q.question_id, type="number", number=1
                ),
            )
        self.assertEqual(
            wrong_type.exception.code, ErrorCode.TYPE_MISMATCH.value
        )


class JumpEvaluationTests(unittest.TestCase):
    def test_single_choice_eq_jump(self) -> None:
        target = "q_five_0005"
        q = single_question(
            logic=logic_with(
                goto_rule(
                    rule_id="r_rule_0001",
                    source_question_id="q_single_0001",
                    operator=ConditionOperator.eq,
                    value=A.option_id,
                    target=target,
                )
            )
        )
        decision = evaluate_jump(q, single_answer(A.option_id))
        self.assertEqual(decision.action, "goto")
        self.assertEqual(decision.target_question_id, target)
        self.assertEqual(decision.matched_rule_id, "r_rule_0001")
        self.assertEqual(
            evaluate_next_question(q, single_answer(A.option_id)), target
        )

        no_match = evaluate_jump(q, single_answer(B.option_id))
        self.assertEqual(no_match.action, "next")
        self.assertIsNone(no_match.target_question_id)
        self.assertIsNone(evaluate_next_question(q, single_answer(B.option_id)))

    def test_not_in_operator(self) -> None:
        target = "q_five_0005"
        q = single_question(
            options=[A, B, C],
            logic=logic_with(
                goto_rule(
                    rule_id="r_rule_0001",
                    source_question_id="q_single_0001",
                    operator=ConditionOperator.not_in,
                    value=[A.option_id, B.option_id],
                    target=target,
                )
            ),
        )
        c_answer = single_answer(C.option_id)
        self.assertIs(validate_answer(q, c_answer), c_answer)
        self.assertEqual(evaluate_next_question(q, c_answer), target)
        self.assertIsNone(
            evaluate_next_question(q, single_answer(A.option_id))
        )

    def test_multi_includes_all_jump(self) -> None:
        target = "q_four_0004"
        q = multi_question(
            logic=logic_with(
                goto_rule(
                    rule_id="r_rule_0002",
                    source_question_id="q_multi_0002",
                    operator=ConditionOperator.includes_all,
                    value=[B.option_id, C.option_id],
                    target=target,
                )
            )
        )
        self.assertEqual(
            evaluate_next_question(
                q, multi_answer([A.option_id, B.option_id, C.option_id])
            ),
            target,
        )
        self.assertIsNone(
            evaluate_next_question(q, multi_answer([B.option_id, D.option_id]))
        )

    def test_number_comparison_jump(self) -> None:
        target = "q_three_0003"
        q = number_question(
            minimum=None,
            maximum=None,
            logic=logic_with(
                goto_rule(
                    rule_id="r_rule_0003",
                    source_question_id="q_number_0003",
                    operator=ConditionOperator.gt,
                    value=18,
                    target=target,
                )
            ),
        )
        self.assertEqual(evaluate_next_question(q, number_answer(19)), target)
        self.assertIsNone(evaluate_next_question(q, number_answer(18)))

    def test_first_matching_rule_wins(self) -> None:
        logic = JumpLogic(
            fallback=FallbackAction(action="next"),
            rules=[
                goto_rule(
                    rule_id="r_rule_0001",
                    source_question_id="q_number_0003",
                    operator=ConditionOperator.gt,
                    value=0,
                    target="q_three_0003",
                ),
                goto_rule(
                    rule_id="r_rule_0002",
                    source_question_id="q_number_0003",
                    operator=ConditionOperator.gt,
                    value=10,
                    target="q_four_0004",
                ),
            ],
        )
        q = number_question(minimum=None, maximum=None, logic=logic)
        self.assertEqual(
            evaluate_next_question(q, number_answer(20)), "q_three_0003"
        )

    def test_all_and_any_condition_groups(self) -> None:
        any_logic = JumpLogic(
            fallback=FallbackAction(action="next"),
            rules=[
                JumpRule(
                    rule_id="r_rule_0005",
                    when=ConditionGroup(
                        mode=ConditionMode.any,
                        conditions=[
                            JumpCondition(
                                question_id="q_number_0003",
                                operator=ConditionOperator.gt,
                                value=10,
                            ),
                            JumpCondition(
                                question_id="q_number_0003",
                                operator=ConditionOperator.lt,
                                value=0,
                            ),
                        ],
                    ),
                    then=GotoAction(
                        action="goto", target_question_id="q_six_0006"
                    ),
                )
            ],
        )
        q = number_question(
            minimum=None, maximum=None, logic=any_logic
        )
        self.assertEqual(
            evaluate_next_question(q, number_answer(20)), "q_six_0006"
        )
        self.assertIsNone(evaluate_next_question(q, number_answer(5)))

    def test_prior_answer_context_and_missing_context(self) -> None:
        previous = single_question()
        previous_answer = single_answer(A.option_id)
        current = number_question(
            minimum=None,
            maximum=None,
            question_id="q_number_0006",
            logic=logic_with(
                goto_rule(
                    rule_id="r_rule_0006",
                    source_question_id=previous.question_id,
                    operator=ConditionOperator.eq,
                    value=A.option_id,
                    target="q_seven_0007",
                )
            ),
        )
        current_answer = number_answer(5, qid=current.question_id)

        self.assertEqual(
            evaluate_next_question(
                current,
                current_answer,
                prior_answers={previous.question_id: previous_answer},
            ),
            "q_seven_0007",
        )
        with self.assertRaises(JumpEvaluationError) as ctx:
            evaluate_next_question(current, current_answer)
        self.assertEqual(
            ctx.exception.code, ErrorCode.ANSWER_CONTEXT_MISSING.value
        )

        # An explicit context around an unanswered question simply makes the
        # condition false; it does not raise.
        self.assertIsNone(
            evaluate_next_question(
                current,
                current_answer,
                prior_answers={},
            )
        )

    def test_fallback_end_and_survey_ended(self) -> None:
        q = number_question(
            minimum=None,
            maximum=None,
            logic=JumpLogic(
                fallback=FallbackAction(action="end"),
                rules=[],
            ),
        )
        decision = evaluate_jump(q, number_answer(1))
        self.assertEqual(decision.action, "end")
        self.assertIsNone(decision.target_question_id)
        with self.assertRaises(SurveyEnded):
            evaluate_next_question(q, number_answer(1))

    def test_rule_can_end_survey(self) -> None:
        q = single_question(
            logic=JumpLogic(
                fallback=FallbackAction(action="next"),
                rules=[
                    JumpRule(
                        rule_id="r_rule_0008",
                        when=ConditionGroup(
                            mode=ConditionMode.all,
                            conditions=[
                                JumpCondition(
                                    question_id="q_single_0001",
                                    operator=ConditionOperator.eq,
                                    value=A.option_id,
                                )
                            ],
                        ),
                        then=EndAction(action="end"),
                    )
                ],
            )
        )
        self.assertEqual(
            evaluate_jump(q, single_answer(A.option_id)).action, "end"
        )

    def test_unanswered_optional_current_means_conditions_are_false(self) -> None:
        q = single_question(
            logic=logic_with(
                goto_rule(
                    rule_id="r_rule_0001",
                    source_question_id="q_single_0001",
                    operator=ConditionOperator.eq,
                    value=A.option_id,
                    target="q_five_0005",
                )
            )
        )
        decision = evaluate_jump(q, None)
        self.assertEqual(decision.action, "next")
        self.assertIsNone(decision.target_question_id)
        self.assertIsNone(decision.matched_rule_id)

    def test_invalid_user_answer_and_missing_operator_are_explicit(self) -> None:
        q = single_question(logic=logic_with())
        with self.assertRaises(JumpEvaluationError) as wrong_answer:
            evaluate_jump(q, number_answer(1, qid="q_other_0001"))
        self.assertEqual(
            wrong_answer.exception.code, ErrorCode.QUESTION_MISMATCH.value
        )

        with self.assertRaises(JumpEvaluationError) as unknown:
            evaluate_operator("does_not_exist", 1, number_answer(1))
        self.assertEqual(
            unknown.exception.code, ErrorCode.UNSUPPORTED_OPERATOR.value
        )

    def test_custom_text_contains_operator_is_pluggable(self) -> None:
        registry = OperatorRegistry.with_default_operators()

        @registry.register("contains", answer_types={"text"})
        def contains(answer, operand):
            return isinstance(answer, TextAnswer) and isinstance(
                operand, str
            ) and operand in answer.text

        text = text_answer("hello world")
        self.assertTrue(
            evaluate_operator(
                "contains", "world", text, registry=registry
            )
        )
        self.assertFalse(
            evaluate_operator(
                "contains", "absent", text, registry=registry
            )
        )

        with self.assertRaises(JumpEvaluationError) as wrong_type:
            registry.evaluate("contains", "1", number_answer(1))
        self.assertEqual(
            wrong_type.exception.code,
            ErrorCode.OPERATOR_TYPE_MISMATCH.value,
        )


if __name__ == "__main__":
    unittest.main()

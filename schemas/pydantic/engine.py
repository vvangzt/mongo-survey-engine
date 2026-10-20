"""Survey-level orchestration built from two pure layers:

1. ``validation.validate_answer`` checks one answer against one question.
2. ``jump.evaluate_jump`` evaluates a question's ordered jump rules.

``validate_submission`` replays the computed display path for whole-page
submissions. The browser may use the same rules for UX, but the server always
recomputes the path and rejects answers for hidden branches.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .errors import ErrorCode, SubmissionValidationError
from .jump import (
    DEFAULT_OPERATOR_REGISTRY,
    JumpDecision,
    OperatorRegistry,
    evaluate_jump,
    evaluate_next_question,
    evaluate_operator,
)
from .models import Answer, Question, Response, SurveyVersion
from .validation import validate_answer

__all__ = [
    "AdvanceResult",
    "DEFAULT_OPERATOR_REGISTRY",
    "JumpDecision",
    "OperatorRegistry",
    "SubmissionResult",
    "SubmissionValidationError",
    "advance_survey",
    "evaluate_jump",
    "evaluate_next_question",
    "evaluate_operator",
    "validate_answer",
    "validate_response",
    "validate_submission",
]


@dataclass(frozen=True)
class SubmissionResult:
    path: tuple[str, ...]
    answers: tuple[Answer, ...]


@dataclass(frozen=True)
class AdvanceResult:
    """Result of computing the next unanswered question for interactive fill."""

    next_question: Question | None
    path: tuple[str, ...]
    completed: bool


def validate_response(
    version: SurveyVersion,
    response: Response,
    *,
    registry: OperatorRegistry | None = None,
) -> SubmissionResult:
    """Validate a response envelope against the exact version it pins."""

    if version.id is None or response.survey_version_id != version.id:
        raise SubmissionValidationError(
            "response.survey_version_id does not match the loaded version"
        )
    return validate_submission(version, response.answers, registry=registry)


def advance_survey(
    version: SurveyVersion,
    answers: Sequence[Answer],
    *,
    skipped_question_ids: Sequence[str] = (),
    registry: OperatorRegistry | None = None,
) -> AdvanceResult:
    """Return the next unanswered question for an interactive fill page.

    The client sends all answers collected so far plus explicitly skipped
    optional question ids. The next question is still computed by the server;
    a browser is never allowed to choose its own branch. The final submission
    must still pass ``validate_submission``.
    """

    positions = {
        question.question_id: index
        for index, question in enumerate(version.questions)
    }
    provided: dict[str, Answer] = {}
    for answer in answers:
        if answer.question_id not in positions:
            raise SubmissionValidationError(
                "answer references a question outside this version: "
                f"{answer.question_id}"
            )
        if answer.question_id in provided:
            raise SubmissionValidationError(
                f"duplicate answer for question {answer.question_id}"
            )
        provided[answer.question_id] = answer

    skipped = set(skipped_question_ids)
    unknown_skips = skipped - set(positions)
    if unknown_skips:
        raise SubmissionValidationError(
            "skip references an unknown question: "
            f"{', '.join(sorted(unknown_skips))}"
        )
    overlapping = skipped & set(provided)
    if overlapping:
        raise SubmissionValidationError(
            "a question cannot be both answered and skipped: "
            f"{', '.join(sorted(overlapping))}"
        )

    visible_answers: dict[str, Answer] = {}
    path: list[str] = []
    index = 0

    while index < len(version.questions):
        question = version.questions[index]
        qid = question.question_id

        if qid in skipped:
            if question.required:
                raise SubmissionValidationError(
                    f"required question cannot be skipped: {qid}",
                    code=ErrorCode.REQUIRED,
                    question_id=qid,
                )
            path.append(qid)
            decision = evaluate_jump(
                question,
                None,
                prior_answers=visible_answers,
                registry=registry,
            )
        else:
            answer = provided.get(qid)
            if answer is None:
                leftover = set(provided) - set(visible_answers)
                if leftover:
                    raise SubmissionValidationError(
                        "answers were supplied for questions not reached on "
                        f"the computed path: {', '.join(sorted(leftover))}"
                    )
                return AdvanceResult(
                    next_question=question,
                    path=tuple(path),
                    completed=False,
                )

            normalized = validate_answer(
                question,
                answer,
                required=question.required,
            )
            assert normalized is not None
            visible_answers[qid] = normalized
            path.append(qid)
            decision = evaluate_jump(
                question,
                normalized,
                prior_answers=visible_answers,
                registry=registry,
            )

        if decision.action == "end":
            break
        if decision.action == "goto":
            target_index = positions.get(decision.target_question_id)
            if target_index is None:
                raise SubmissionValidationError(
                    "jump target does not exist in this version: "
                    f"{decision.target_question_id}"
                )
            if target_index <= index:
                raise SubmissionValidationError(
                    "stored jump logic attempts a backward or self jump; "
                    "the version is invalid"
                )
            index = target_index
            continue
        index += 1

    leftover = set(provided) - set(visible_answers)
    if leftover:
        raise SubmissionValidationError(
            "answers were supplied for questions not visible on the computed "
            f"path: {', '.join(sorted(leftover))}"
        )
    skipped_not_seen = skipped - set(path)
    if skipped_not_seen:
        raise SubmissionValidationError(
            "skip references a question outside the computed path: "
            f"{', '.join(sorted(skipped_not_seen))}"
        )
    return AdvanceResult(
        next_question=None,
        path=tuple(path),
        completed=True,
    )


def validate_submission(
    version: SurveyVersion,
    answers: Sequence[Answer],
    *,
    registry: OperatorRegistry | None = None,
) -> SubmissionResult:
    """Replay the survey path, validate visible answers, and canonicalize them.

    - Optional questions may be unanswered.
    - Required questions are required only when the computed path displays them.
    - Duplicate answers, answers for unknown questions, and answers for skipped
      (not displayed) questions are rejected.
    - Text is trimmed when configured, and the normalized answers are returned
      in display order. Persist this result rather than the raw request body.
    """

    positions = {
        question.question_id: index
        for index, question in enumerate(version.questions)
    }
    provided: dict[str, Answer] = {}
    for answer in answers:
        if answer.question_id not in positions:
            raise SubmissionValidationError(
                "answer references a question outside this version: "
                f"{answer.question_id}"
            )
        if answer.question_id in provided:
            raise SubmissionValidationError(
                f"duplicate answer for question {answer.question_id}"
            )
        provided[answer.question_id] = answer

    visible_answers: dict[str, Answer] = {}
    ordered_answers: list[Answer] = []
    path: list[str] = []
    index = 0

    while index < len(version.questions):
        question = version.questions[index]
        answer = provided.get(question.question_id)

        normalized = validate_answer(
            question,
            answer,
            required=question.required,
        )
        if normalized is not None:
            visible_answers[question.question_id] = normalized
            ordered_answers.append(normalized)

        path.append(question.question_id)

        decision = evaluate_jump(
            question,
            visible_answers.get(question.question_id),
            prior_answers=visible_answers,
            registry=registry,
        )
        if decision.action == "end":
            break
        if decision.action == "goto":
            target_index = positions.get(decision.target_question_id)
            if target_index is None:
                raise SubmissionValidationError(
                    f"jump target does not exist in this version: "
                    f"{decision.target_question_id}"
                )
            if target_index <= index:
                raise SubmissionValidationError(
                    "stored jump logic attempts a backward or self jump; "
                    "the version is invalid"
                )
            index = target_index
            continue
        index += 1

    leftover = set(provided) - set(visible_answers)
    if leftover:
        raise SubmissionValidationError(
            "answers were supplied for questions not visible on the computed "
            f"path: {', '.join(sorted(leftover))}"
        )

    return SubmissionResult(path=tuple(path), answers=tuple(ordered_answers))

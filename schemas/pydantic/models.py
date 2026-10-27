"""Pydantic v2 models for the questionnaire MongoDB design.

The canonical JSON Schema lives in ../json-schema. These models are the
FastAPI-facing executable contract and intentionally mirror it field for field.
Persisted BSON documents are converted to/from these models at the repository
boundary. All timestamps in this contract are timezone-aware and stored in UTC.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Literal, Union

from bson import ObjectId
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

SAFE_INT_MIN = -9007199254740991
SAFE_INT_MAX = 9007199254740991
MAX_QUESTIONS = 300
MAX_OPTIONS = 100
MAX_TEXT_ANSWER_LENGTH = 5000
MAX_CONDITIONS = 50
MAX_RULES = 50

ObjectIdStr = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-fA-F]{24}$")
]
UtcDateTime = AwareDatetime
Slug = Annotated[
    str,
    StringConstraints(
        pattern=r"^[a-z0-9](?:[a-z0-9-]{4,61}[a-z0-9])$",
        min_length=6,
        max_length=63,
    ),
]
Email = Annotated[
    str,
    StringConstraints(
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        min_length=3,
        max_length=254,
    ),
]
Username = Annotated[
    str,
    StringConstraints(
        pattern=r"^[a-z0-9_]{3,32}$",
        min_length=3,
        max_length=32,
    ),
]
QuestionId = Annotated[
    str, StringConstraints(pattern=r"^q_[A-Za-z0-9_-]{8,64}$")
]
OptionId = Annotated[
    str, StringConstraints(pattern=r"^o_[A-Za-z0-9_-]{8,64}$")
]
RuleId = Annotated[
    str, StringConstraints(pattern=r"^r_[A-Za-z0-9_-]{8,64}$")
]
SubmissionToken = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{16,128}$")
]
ContentHash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
NumberValue = Union[StrictInt, FiniteFloat]


def _object_id_str(value: object) -> object:
    """Accept a BSON ObjectId (straight from MongoDB) as its hex string.

    Documents are read from PyMongo with real ObjectId values, while the HTTP
    contract only knows hex strings. Coercing once at the boundary keeps both
    sides honest without weakening the pattern check.
    """

    if isinstance(value, ObjectId):
        return str(value)
    return value


ObjectIdRef = Annotated[
    str,
    BeforeValidator(_object_id_str),
    StringConstraints(pattern=r"^[0-9a-fA-F]{24}$"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MongoDocument(StrictModel):
    id: ObjectIdStr | None = Field(default=None, alias="_id")
    schema_version: Literal[1] = 1


class UserStatus(str, Enum):
    active = "active"
    disabled = "disabled"


class SurveyStatus(str, Enum):
    draft = "draft"
    published = "published"
    closed = "closed"


class VersionState(str, Enum):
    draft = "draft"
    published = "published"


class ConditionMode(str, Enum):
    all = "all"
    any = "any"


class ConditionOperator(str, Enum):
    eq = "eq"
    neq = "neq"
    in_ = "in"
    not_in = "not_in"
    includes_any = "includes_any"
    includes_all = "includes_all"
    includes_none = "includes_none"
    equals_set = "equals_set"
    selection_count_eq = "selection_count_eq"
    selection_count_gte = "selection_count_gte"
    selection_count_lte = "selection_count_lte"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    between = "between"


class Option(StrictModel):
    option_id: OptionId
    label: str = Field(min_length=1, max_length=500)


class MultiChoiceValidation(StrictModel):
    min_selected: int | None = Field(default=None, ge=0, le=MAX_OPTIONS)
    max_selected: int | None = Field(default=None, ge=1, le=MAX_OPTIONS)
    exact_selected: int | None = Field(default=None, ge=1, le=MAX_OPTIONS)

    @model_validator(mode="after")
    def check_constraints(self) -> "MultiChoiceValidation":
        if self.exact_selected is not None and (
            self.min_selected is not None or self.max_selected is not None
        ):
            raise ValueError(
                "exact_selected cannot be combined with min_selected/max_selected"
            )
        if (
            self.min_selected is not None
            and self.max_selected is not None
            and self.min_selected > self.max_selected
        ):
            raise ValueError("min_selected must be <= max_selected")
        return self


class TextValidation(StrictModel):
    min_length: int = Field(default=0, ge=0, le=MAX_TEXT_ANSWER_LENGTH)
    max_length: int = Field(ge=1, le=MAX_TEXT_ANSWER_LENGTH)
    trim: bool = True

    @model_validator(mode="after")
    def check_lengths(self) -> "TextValidation":
        if self.min_length > self.max_length:
            raise ValueError("min_length must be <= max_length")
        return self


class NumberValidation(StrictModel):
    integer: bool = True
    min: NumberValue | None = None
    max: NumberValue | None = None

    @model_validator(mode="after")
    def check_bounds(self) -> "NumberValidation":
        for bound in (self.min, self.max):
            if bound is not None and (
                isinstance(bound, bool)
                or not isinstance(bound, (int, float))
                or not math.isfinite(float(bound))
            ):
                raise ValueError("numeric bounds must be finite numbers")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class FallbackAction(StrictModel):
    action: Literal["next", "end"]


class GotoAction(StrictModel):
    action: Literal["goto"]
    target_question_id: QuestionId


class EndAction(StrictModel):
    action: Literal["end"]


RuleAction = Annotated[
    Union[GotoAction, EndAction], Field(discriminator="action")
]

# Smart-union order matters for list values: a list of integers must be tried
# before a list of string-like option IDs.
ConditionValue = Union[
    OptionId,
    NumberValue,
    list[NumberValue],
    list[OptionId],
]


class JumpCondition(StrictModel):
    question_id: QuestionId
    operator: ConditionOperator
    value: ConditionValue


class ConditionGroup(StrictModel):
    mode: ConditionMode
    conditions: list[JumpCondition] = Field(
        min_length=1, max_length=MAX_CONDITIONS
    )


class JumpRule(StrictModel):
    rule_id: RuleId
    when: ConditionGroup
    then: RuleAction


class JumpLogic(StrictModel):
    fallback: FallbackAction
    rules: list[JumpRule] = Field(default_factory=list, max_length=MAX_RULES)


class QuestionRef(StrictModel):
    """Pointers from a survey-embedded question to the shared question library.

    ``entity_id`` is the stable cross-survey identity of the question;
    ``version_id`` is the immutable content version that this survey version
    pinned. Both are optional on the surrounding documents so that phase-1
    data, which has no library reference at all, stays valid.
    """

    entity_id: ObjectIdRef
    version_id: ObjectIdRef


class QuestionBase(StrictModel):
    question_id: QuestionId
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    required: bool = False
    logic: JumpLogic | None = None
    question_ref: QuestionRef | None = None

    @property
    def jump_rules(self) -> tuple[JumpRule, ...]:
        """Read-only alias for the persisted ``logic.rules`` array."""

        return tuple(self.logic.rules) if self.logic is not None else ()


def _ensure_unique_options(options: list[Option]) -> list[Option]:
    option_ids = [option.option_id for option in options]
    if len(set(option_ids)) != len(option_ids):
        raise ValueError("option_id values must be unique within a question")
    return options


class SingleChoiceQuestion(QuestionBase):
    type: Literal["single_choice"]
    options: list[Option] = Field(min_length=2, max_length=MAX_OPTIONS)

    @field_validator("options")
    @classmethod
    def unique_options(cls, value: list[Option]) -> list[Option]:
        return _ensure_unique_options(value)


class MultiChoiceQuestion(QuestionBase):
    type: Literal["multi_choice"]
    options: list[Option] = Field(min_length=2, max_length=MAX_OPTIONS)
    validation: MultiChoiceValidation

    @field_validator("options")
    @classmethod
    def unique_options(cls, value: list[Option]) -> list[Option]:
        return _ensure_unique_options(value)

    @model_validator(mode="after")
    def check_option_bounds(self) -> "MultiChoiceQuestion":
        configured = [
            self.validation.min_selected,
            self.validation.max_selected,
            self.validation.exact_selected,
        ]
        for value in configured:
            if value is not None and value > len(self.options):
                raise ValueError(
                    "selection constraint cannot exceed the number of options"
                )
        return self


class TextQuestion(QuestionBase):
    type: Literal["text"]
    validation: TextValidation


class NumberQuestion(QuestionBase):
    type: Literal["number"]
    validation: NumberValidation


Question = Annotated[
    Union[
        SingleChoiceQuestion,
        MultiChoiceQuestion,
        TextQuestion,
        NumberQuestion,
    ],
    Field(discriminator="type"),
]


class User(MongoDocument):
    username: Username
    email: Email
    password_hash: str = Field(min_length=20, max_length=255)
    display_name: str = Field(min_length=1, max_length=80)
    status: UserStatus = UserStatus.active
    last_login_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class Survey(MongoDocument):
    owner_id: ObjectIdStr
    slug: Slug
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    status: SurveyStatus = SurveyStatus.draft
    allow_anonymous: bool = False
    allow_multiple_responses: bool = True
    opens_at: UtcDateTime | None = None
    closes_at: UtcDateTime | None = None
    current_draft_version_id: ObjectIdStr | None = None
    published_version_id: ObjectIdStr | None = None
    last_version_no: int = Field(default=0, ge=0)
    published_at: UtcDateTime | None = None
    closed_at: UtcDateTime | None = None
    deleted_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @model_validator(mode="after")
    def check_lifecycle(self) -> "Survey":
        if (
            self.opens_at is not None
            and self.closes_at is not None
            and self.opens_at >= self.closes_at
        ):
            raise ValueError("opens_at must be earlier than closes_at")
        if self.status is SurveyStatus.published and (
            self.published_version_id is None or self.published_at is None
        ):
            raise ValueError(
                "a published survey requires published_version_id and published_at"
            )
        if self.status is SurveyStatus.closed and self.published_version_id is None:
            raise ValueError("a closed survey must retain its published version")
        return self


def _validate_condition_value(
    source: QuestionBase, operator: ConditionOperator, value: object
) -> None:
    """Validate an operator/value pair against the source question type.

    This is deliberately a semantic (cross-field) check: JSON Schema cannot
    express that, for example, `between` only accepts a two-integer array.
    """

    def is_int(candidate: object) -> bool:
        return isinstance(candidate, int) and not isinstance(candidate, bool)

    def is_number(candidate: object) -> bool:
        return (
            isinstance(candidate, (int, float))
            and not isinstance(candidate, bool)
            and math.isfinite(float(candidate))
        )

    if isinstance(source, SingleChoiceQuestion):
        valid_option_ids = {option.option_id for option in source.options}
        if operator in {ConditionOperator.eq, ConditionOperator.neq}:
            if not isinstance(value, str) or value not in valid_option_ids:
                raise ValueError(
                    f"{operator.value} requires an existing option_id "
                    f"for single-choice question {source.question_id}"
                )
            return
        if operator in {ConditionOperator.in_, ConditionOperator.not_in}:
            if (
                not isinstance(value, list)
                or not value
                or any(not isinstance(item, str) for item in value)
                or len(set(value)) != len(value)
                or any(item not in valid_option_ids for item in value)
            ):
                raise ValueError(
                    f"{operator.value} requires a unique, non-empty list of "
                    f"existing option_ids for {source.question_id}"
                )
            return
        raise ValueError(
            f"operator {operator.value} is not valid for single_choice"
        )

    if isinstance(source, MultiChoiceQuestion):
        valid_option_ids = {option.option_id for option in source.options}
        if operator in {
            ConditionOperator.includes_any,
            ConditionOperator.includes_all,
            ConditionOperator.includes_none,
            ConditionOperator.equals_set,
        }:
            if (
                not isinstance(value, list)
                or not value
                or any(not isinstance(item, str) for item in value)
                or len(set(value)) != len(value)
                or any(item not in valid_option_ids for item in value)
            ):
                raise ValueError(
                    f"{operator.value} requires a unique, non-empty list of "
                    f"existing option_ids for {source.question_id}"
                )
            return
        if operator in {
            ConditionOperator.selection_count_eq,
            ConditionOperator.selection_count_gte,
            ConditionOperator.selection_count_lte,
        }:
            if not is_int(value) or value < 0 or value > len(source.options):
                raise ValueError(
                    f"{operator.value} requires an integer in [0, "
                    f"{len(source.options)}] for {source.question_id}"
                )
            return
        raise ValueError(
            f"operator {operator.value} is not valid for multi_choice"
        )

    if isinstance(source, NumberQuestion):
        if operator in {
            ConditionOperator.eq,
            ConditionOperator.neq,
            ConditionOperator.gt,
            ConditionOperator.gte,
            ConditionOperator.lt,
            ConditionOperator.lte,
        }:
            if not is_number(value):
                raise ValueError(
                    f"{operator.value} requires a finite number for "
                    f"{source.question_id}"
                )
            return
        if operator is ConditionOperator.between:
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(not is_number(item) for item in value)
                or value[0] > value[1]
            ):
                raise ValueError(
                    f"between requires an ordered [low, high] number pair "
                    f"for {source.question_id}"
                )
            return
        raise ValueError(f"operator {operator.value} is not valid for number")

    raise TypeError(f"unsupported question type: {type(source)!r}")


class SurveyVersion(MongoDocument):
    survey_id: ObjectIdStr
    version_no: int = Field(ge=1)
    state: VersionState
    content_schema_version: Literal[1, 2] = 1
    revision: int = Field(ge=1)
    questions: list[Question] = Field(
        min_length=1, max_length=MAX_QUESTIONS
    )
    created_by: ObjectIdStr
    created_at: UtcDateTime
    updated_at: UtcDateTime
    published_at: UtcDateTime | None = None
    content_hash: ContentHash | None = None

    @model_validator(mode="after")
    def check_publish_and_logic(self) -> "SurveyVersion":
        question_ids = [question.question_id for question in self.questions]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("question_id values must be unique in a version")

        positions = {
            question.question_id: index
            for index, question in enumerate(self.questions)
        }

        for index, question in enumerate(self.questions):
            if question.logic is None:
                continue

            rule_ids = [rule.rule_id for rule in question.logic.rules]
            if len(set(rule_ids)) != len(rule_ids):
                raise ValueError(
                    f"rule_id values must be unique within {question.question_id}"
                )

            for rule in question.logic.rules:
                for condition in rule.when.conditions:
                    if condition.question_id not in positions:
                        raise ValueError(
                            f"condition references unknown question "
                            f"{condition.question_id}"
                        )
                    source_index = positions[condition.question_id]
                    if source_index > index:
                        raise ValueError(
                            "jump conditions may reference only the current or "
                            f"an earlier question: {condition.question_id} "
                            f"referenced by {question.question_id}"
                        )
                    source = self.questions[source_index]
                    _validate_condition_value(
                        source, condition.operator, condition.value
                    )

                if isinstance(rule.then, GotoAction):
                    target = rule.then.target_question_id
                    if target not in positions:
                        raise ValueError(f"jump target {target} does not exist")
                    if positions[target] <= index:
                        raise ValueError(
                            "goto targets must point forward and cannot create "
                            f"cycles: {question.question_id} -> {target}"
                        )

        if self.state is VersionState.published:
            if self.published_at is None or self.content_hash is None:
                raise ValueError(
                    "a published version requires published_at and content_hash"
                )
        return self


class AnswerBase(StrictModel):
    question_id: QuestionId
    question_ref: QuestionRef | None = None


class SingleChoiceAnswer(AnswerBase):
    type: Literal["single_choice"]
    option_ids: list[OptionId] = Field(min_length=1, max_length=1)


class MultiChoiceAnswer(AnswerBase):
    type: Literal["multi_choice"]
    option_ids: list[OptionId] = Field(
        min_length=1, max_length=MAX_OPTIONS
    )

    @field_validator("option_ids")
    @classmethod
    def unique_option_ids(cls, value: list[OptionId]) -> list[OptionId]:
        if len(set(value)) != len(value):
            raise ValueError("option_ids must not contain duplicates")
        return value


class TextAnswer(AnswerBase):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=MAX_TEXT_ANSWER_LENGTH)


class NumberAnswer(AnswerBase):
    type: Literal["number"]
    number: NumberValue


Answer = Annotated[
    Union[
        SingleChoiceAnswer,
        MultiChoiceAnswer,
        TextAnswer,
        NumberAnswer,
    ],
    Field(discriminator="type"),
]


class Response(MongoDocument):
    survey_id: ObjectIdStr
    survey_version_id: ObjectIdStr
    respondent_id: ObjectIdStr | None = None
    is_anonymous: bool
    submission_token: SubmissionToken
    answers: list[Answer] = Field(
        default_factory=list, max_length=MAX_QUESTIONS
    )
    submitted_at: UtcDateTime

    @model_validator(mode="after")
    def check_identity_and_answers(self) -> "Response":
        if self.is_anonymous and self.respondent_id is not None:
            raise ValueError("anonymous responses must not carry respondent_id")
        if not self.is_anonymous and self.respondent_id is None:
            raise ValueError("identified responses require respondent_id")

        question_ids = [answer.question_id for answer in self.answers]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("a response may answer each question at most once")
        return self


class OptionCount(StrictModel):
    option_id: OptionId
    count: int = Field(ge=0)


class ChoiceQuestionStats(StrictModel):
    question_id: QuestionId
    question_type: Literal["single_choice", "multi_choice"]
    answered_count: int = Field(ge=0)
    option_counts: list[OptionCount] = Field(max_length=MAX_OPTIONS)


class TextQuestionStats(StrictModel):
    question_id: QuestionId
    question_type: Literal["text"]
    answered_count: int = Field(ge=0)


class NumericStats(StrictModel):
    sum: NumberValue
    avg: float
    min: NumberValue
    max: NumberValue


class NumberQuestionStats(StrictModel):
    question_id: QuestionId
    question_type: Literal["number"]
    answered_count: int = Field(ge=0)
    numeric_stats: NumericStats | None


QuestionStats = Annotated[
    Union[ChoiceQuestionStats, TextQuestionStats, NumberQuestionStats],
    Field(discriminator="question_type"),
]


class SurveyStatSnapshot(MongoDocument):
    survey_id: ObjectIdStr
    survey_version_id: ObjectIdStr
    response_count: int = Field(ge=0)
    questions: list[QuestionStats] = Field(
        min_length=1, max_length=MAX_QUESTIONS
    )
    latest_submitted_at: UtcDateTime | None = None
    computed_at: UtcDateTime


__all__ = [
    "Answer",
    "ChoiceQuestionStats",
    "ConditionGroup",
    "ConditionMode",
    "ConditionOperator",
    "ContentHash",
    "Email",
    "EndAction",
    "FallbackAction",
    "GotoAction",
    "JumpCondition",
    "JumpLogic",
    "JumpRule",
    "MultiChoiceAnswer",
    "MultiChoiceQuestion",
    "MultiChoiceValidation",
    "NumberAnswer",
    "NumberQuestion",
    "NumberQuestionStats",
    "NumberValidation",
    "NumberValue",
    "NumericStats",
    "ObjectIdRef",
    "ObjectIdStr",
    "Option",
    "OptionCount",
    "OptionId",
    "Question",
    "QuestionBase",
    "QuestionId",
    "QuestionRef",
    "Response",
    "RuleAction",
    "RuleId",
    "SingleChoiceAnswer",
    "SingleChoiceQuestion",
    "Slug",
    "SubmissionToken",
    "Survey",
    "SurveyStatSnapshot",
    "SurveyStatus",
    "SurveyVersion",
    "TextAnswer",
    "TextQuestion",
    "TextQuestionStats",
    "TextValidation",
    "User",
    "UserStatus",
    "Username",
    "UtcDateTime",
    "VersionState",
]

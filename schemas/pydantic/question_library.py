"""Question library domain models: entities, immutable versions, shares, banks.

Phase 2 extracts questions out of ``survey_versions`` so that one question can be
reused by many surveys. The split is:

``questions``            mutable identity + ownership + visibility
``question_versions``    immutable content snapshots (v1 -> v2 -> v3)
``question_shares``      per-user grants
``question_libraries``   named collections (question banks)
``question_library_items``  membership of a question in a bank

A survey version keeps the full question content inline (that is the frozen
snapshot the survey renders, validates and counts) and adds a ``question_ref``
pointer. The two are kept consistent by the content hash: see
``docs/第二阶段/数据模型变更说明.md`` invariant I2.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from enum import Enum
from typing import Any, Literal, Union

from pydantic import Field, field_validator, model_validator

from .models import (
    MAX_OPTIONS,
    ContentHash,
    MongoDocument,
    MultiChoiceQuestion,
    MultiChoiceValidation,
    NumberQuestion,
    NumberValidation,
    ObjectIdRef,
    Option,
    Question,
    QuestionRef,
    SingleChoiceQuestion,
    StrictModel,
    TextQuestion,
    TextValidation,
    UtcDateTime,
)

QuestionTypeName = Literal["single_choice", "multi_choice", "text", "number"]

# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------


class QuestionVisibility(str, Enum):
    """Who may see and use a question.

    ``private``  only the owner
    ``shared``   owner plus explicit ``question_shares`` grants
    ``public``   any signed-in user (useful for a shared team/class bank)
    """

    private = "private"
    shared = "shared"
    public = "public"


class SharePermission(str, Enum):
    view = "view"
    use = "use"


class LibraryVisibility(str, Enum):
    private = "private"
    public = "public"


# ---------------------------------------------------------------------------
# question content (the part that is versioned)
# ---------------------------------------------------------------------------


def _ensure_unique_options(options: list[Option]) -> list[Option]:
    option_ids = [option.option_id for option in options]
    if len(set(option_ids)) != len(option_ids):
        raise ValueError("option_id values must be unique within a question")
    return options


class QuestionContentBase(StrictModel):
    """Everything that belongs to the question itself.

    Deliberately excludes ``question_id`` (an instance id inside one survey
    version) and ``logic`` (jump rules depend on the survey's position), so the
    same content can be inserted into any survey.
    """

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    required: bool = False


class SingleChoiceContent(QuestionContentBase):
    type: Literal["single_choice"]
    options: list[Option] = Field(min_length=2, max_length=MAX_OPTIONS)

    @field_validator("options")
    @classmethod
    def unique_options(cls, value: list[Option]) -> list[Option]:
        return _ensure_unique_options(value)


class MultiChoiceContent(QuestionContentBase):
    type: Literal["multi_choice"]
    options: list[Option] = Field(min_length=2, max_length=MAX_OPTIONS)
    validation: MultiChoiceValidation

    @field_validator("options")
    @classmethod
    def unique_options(cls, value: list[Option]) -> list[Option]:
        return _ensure_unique_options(value)

    @model_validator(mode="after")
    def check_option_bounds(self) -> "MultiChoiceContent":
        for value in (
            self.validation.min_selected,
            self.validation.max_selected,
            self.validation.exact_selected,
        ):
            if value is not None and value > len(self.options):
                raise ValueError(
                    "selection constraint cannot exceed the number of options"
                )
        return self


class TextContent(QuestionContentBase):
    type: Literal["text"]
    validation: TextValidation


class NumberContent(QuestionContentBase):
    type: Literal["number"]
    validation: NumberValidation


QuestionContent = Union[
    SingleChoiceContent,
    MultiChoiceContent,
    TextContent,
    NumberContent,
]

CONTENT_MODELS: dict[str, Any] = {
    "single_choice": SingleChoiceContent,
    "multi_choice": MultiChoiceContent,
    "text": TextContent,
    "number": NumberContent,
}

QUESTION_MODELS: dict[str, Any] = {
    "single_choice": SingleChoiceQuestion,
    "multi_choice": MultiChoiceQuestion,
    "text": TextQuestion,
    "number": NumberQuestion,
}


# ---------------------------------------------------------------------------
# content helpers
# ---------------------------------------------------------------------------


def canonical_content(content: QuestionContent) -> dict[str, Any]:
    """Canonical JSON-ready form used for hashing and for comparisons."""

    data = content.model_dump(mode="json", exclude_none=True)
    # ``type`` is the discriminator and must stay in the payload.
    return data


def hash_content(content: QuestionContent) -> str:
    payload = json.dumps(
        canonical_content(content), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def content_of(question: Question) -> QuestionContent:
    """Extract the versioned content out of a survey-embedded question."""

    data = question.model_dump(mode="json", exclude_none=True)
    for key in ("question_id", "logic", "question_ref"):
        data.pop(key, None)
    model = CONTENT_MODELS.get(question.type)
    if model is None:  # pragma: no cover - guarded by the Question union
        raise ValueError(f"unsupported question type: {question.type}")
    return model.model_validate(data)


def question_from_content(
    content: QuestionContent,
    question_id: str,
    logic: Any | None = None,
) -> Question:
    """Materialise a survey-embedded question from library content."""

    data = content.model_dump(mode="json", exclude_none=True)
    data["question_id"] = question_id
    if logic is not None:
        data["logic"] = logic
    model = QUESTION_MODELS[content.type]
    return model.model_validate(data)


def content_matches(
    question: Question, content: QuestionContent
) -> bool:
    """True when a survey-embedded question still equals the library content."""

    try:
        return hash_content(content_of(question)) == hash_content(content)
    except Exception:  # pragma: no cover - malformed legacy payloads
        return False


def new_option_id() -> str:
    return f"o_{uuid.uuid4().hex[:16]}"


def merge_option_ids(
    previous: list[Option], incoming: list[Option]
) -> list[Option]:
    """Keep ``option_id`` stable across versions of the same question (I6).

    Rules, in order:
    1. an id that already existed is kept;
    2. otherwise an option with the same label inherits the old id;
    3. otherwise the incoming id is kept (or regenerated on a collision).

    Renaming an option label therefore reads as "old option removed, new option
    added". Cross-version statistics stay meaningful because unchanged options
    keep their identity.
    """

    previous_by_id = {option.option_id: option for option in previous}
    previous_by_label: dict[str, str] = {}
    for option in previous:
        previous_by_label.setdefault(option.label, option.option_id)

    used: set[str] = set()
    merged: list[Option] = []
    for option in incoming:
        option_id = option.option_id
        if option_id in previous_by_id and option_id not in used:
            used.add(option_id)
            merged.append(Option(option_id=option_id, label=option.label))
            continue

        inherited = previous_by_label.get(option.label)
        if inherited is not None and inherited not in used:
            used.add(inherited)
            merged.append(Option(option_id=inherited, label=option.label))
            continue

        if option_id in used:
            option_id = new_option_id()
        used.add(option_id)
        merged.append(Option(option_id=option_id, label=option.label))
    return merged


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------


class QuestionEntity(MongoDocument):
    """Stable, cross-survey identity of one question."""

    owner_id: ObjectIdRef
    root_entity_id: ObjectIdRef
    source_entity_id: ObjectIdRef | None = None
    source_version_id: ObjectIdRef | None = None
    lineage_depth: int = Field(default=0, ge=0)
    type: QuestionTypeName
    title: str = Field(min_length=1, max_length=500)
    visibility: QuestionVisibility = QuestionVisibility.private
    latest_version_id: ObjectIdRef
    latest_version_no: int = Field(ge=1)
    version_count: int = Field(ge=1)
    deleted_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class QuestionVersion(MongoDocument):
    """Immutable content snapshot. There is no code path that updates it."""

    entity_id: ObjectIdRef
    version_no: int = Field(ge=1)
    parent_version_id: ObjectIdRef | None = None
    restored_from_version_id: ObjectIdRef | None = None
    content: QuestionContent
    content_hash: ContentHash
    created_by: ObjectIdRef
    created_at: UtcDateTime
    legacy_key: str | None = None

    @model_validator(mode="after")
    def check_hash(self) -> "QuestionVersion":
        expected = hash_content(self.content)
        if expected != self.content_hash:
            raise ValueError(
                "content_hash does not match the version content"
            )
        if self.version_no == 1 and self.parent_version_id is not None:
            raise ValueError("the first version cannot have a parent")
        if self.version_no > 1 and self.parent_version_id is None:
            raise ValueError("a later version requires parent_version_id")
        return self


class QuestionShare(MongoDocument):
    entity_id: ObjectIdRef
    grantee_id: ObjectIdRef
    permission: SharePermission = SharePermission.use
    granted_by: ObjectIdRef
    created_at: UtcDateTime


class QuestionLibrary(MongoDocument):
    owner_id: ObjectIdRef
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    visibility: LibraryVisibility = LibraryVisibility.private
    created_at: UtcDateTime
    updated_at: UtcDateTime


class QuestionLibraryItem(MongoDocument):
    library_id: ObjectIdRef
    entity_id: ObjectIdRef
    added_by: ObjectIdRef
    added_at: UtcDateTime
    note: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("tags")
    @classmethod
    def check_tags(cls, value: list[str]) -> list[str]:
        for tag in value:
            if not tag or len(tag) > 32:
                raise ValueError("each tag must be 1..32 characters")
        if len(set(value)) != len(value):
            raise ValueError("tags must not contain duplicates")
        return value


__all__ = [
    "CONTENT_MODELS",
    "LibraryVisibility",
    "MultiChoiceContent",
    "NumberContent",
    "QUESTION_MODELS",
    "QuestionContent",
    "QuestionContentBase",
    "QuestionEntity",
    "QuestionLibrary",
    "QuestionLibraryItem",
    "QuestionRef",
    "QuestionShare",
    "QuestionVersion",
    "QuestionVisibility",
    "SharePermission",
    "SingleChoiceContent",
    "TextContent",
    "canonical_content",
    "content_matches",
    "content_of",
    "hash_content",
    "merge_option_ids",
    "new_option_id",
    "question_from_content",
]

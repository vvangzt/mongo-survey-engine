"""MongoDB index creation shared by the application and init script."""

from __future__ import annotations

from pymongo.asynchronous.database import AsyncDatabase


async def create_indexes(db: AsyncDatabase) -> None:
    """Create all indexes required by the application.

    Index creation is idempotent. It is invoked on startup in the course
    project (AUTO_CREATE_INDEXES=true) and can also be run explicitly via
    ``python -m backend.database``.
    """

    await db["users"].create_index(
        "username", unique=True, name="ux_users_username"
    )
    await db["users"].create_index(
        "email", unique=True, name="ux_users_email"
    )

    await db["surveys"].create_index(
        "slug", unique=True, name="ux_surveys_slug"
    )
    await db["surveys"].create_index(
        [("owner_id", 1), ("created_at", -1)],
        name="ix_surveys_owner_created",
    )
    await db["surveys"].create_index(
        [("status", 1), ("closes_at", 1)],
        name="ix_surveys_status_close",
    )

    await db["survey_versions"].create_index(
        [("survey_id", 1), ("version_no", 1)],
        unique=True,
        name="ux_versions_survey_version_no",
    )
    await db["survey_versions"].create_index(
        [("survey_id", 1), ("state", 1)],
        name="ix_versions_survey_state",
    )

    await db["responses"].create_index(
        [("survey_id", 1), ("submission_token", 1)],
        unique=True,
        name="ux_responses_survey_token",
    )
    await db["responses"].create_index(
        [("survey_id", 1), ("submitted_at", -1)],
        name="ix_responses_survey_submitted",
    )
    await db["responses"].create_index(
        [("survey_id", 1), ("survey_version_id", 1), ("submitted_at", -1)],
        name="ix_responses_survey_version_submitted",
    )
    await db["responses"].create_index(
        [("survey_id", 1), ("survey_version_id", 1), ("answers.question_id", 1)],
        name="ix_responses_survey_version_question",
    )
    await db["responses"].create_index(
        [("survey_id", 1), ("respondent_id", 1)],
        name="ix_responses_survey_respondent",
        partialFilterExpression={"respondent_id": {"$type": "objectId"}},
    )

    await db["survey_stat_snapshots"].create_index(
        [("survey_id", 1), ("survey_version_id", 1)],
        unique=True,
        name="ux_stats_survey_version",
    )

    # ------------------------------------------------------------------
    # Phase 2: shared question library
    # ------------------------------------------------------------------

    await db["questions"].create_index(
        [("owner_id", 1), ("updated_at", -1)],
        name="ix_questions_owner_updated",
    )
    await db["questions"].create_index(
        [("root_entity_id", 1)],
        name="ix_questions_root",
    )
    await db["questions"].create_index(
        [("owner_id", 1), ("type", 1), ("deleted_at", 1)],
        name="ix_questions_owner_type_deleted",
    )

    await db["question_versions"].create_index(
        [("entity_id", 1), ("version_no", 1)],
        unique=True,
        name="ux_qversions_entity_version_no",
    )
    await db["question_versions"].create_index(
        [("entity_id", 1), ("created_at", -1)],
        name="ix_qversions_entity_created",
    )
    await db["question_versions"].create_index(
        [("parent_version_id", 1)],
        name="ix_qversions_parent",
    )
    await db["question_versions"].create_index(
        [("legacy_key", 1)],
        unique=True,
        name="ux_qversions_legacy_key",
        partialFilterExpression={"legacy_key": {"$type": "string"}},
    )

    await db["question_shares"].create_index(
        [("entity_id", 1), ("grantee_id", 1)],
        unique=True,
        name="ux_shares_entity_grantee",
    )
    await db["question_shares"].create_index(
        [("grantee_id", 1), ("created_at", -1)],
        name="ix_shares_grantee_created",
    )

    await db["question_libraries"].create_index(
        [("owner_id", 1), ("name", 1)],
        unique=True,
        name="ux_libraries_owner_name",
    )
    await db["question_libraries"].create_index(
        [("owner_id", 1), ("updated_at", -1)],
        name="ix_libraries_owner_updated",
    )
    await db["question_libraries"].create_index(
        [("visibility", 1), ("updated_at", -1)],
        name="ix_libraries_visibility_updated",
    )

    await db["question_library_items"].create_index(
        [("library_id", 1), ("entity_id", 1)],
        unique=True,
        name="ux_litems_library_entity",
    )
    await db["question_library_items"].create_index(
        [("library_id", 1), ("added_at", -1)],
        name="ix_litems_library_added",
    )
    await db["question_library_items"].create_index(
        [("entity_id", 1)],
        name="ix_litems_entity",
    )

    # Multikey indexes that make "which surveys use this question" (reverse
    # lookup) and "statistics for one question across surveys" index-only
    # narrowing scans instead of collection scans.
    await db["survey_versions"].create_index(
        [("questions.question_ref.entity_id", 1)],
        name="ix_versions_question_entity",
    )
    await db["survey_versions"].create_index(
        [("questions.question_ref.version_id", 1)],
        name="ix_versions_question_version",
    )
    await db["responses"].create_index(
        [("answers.question_ref.entity_id", 1), ("submitted_at", -1)],
        name="ix_responses_answer_entity_submitted",
    )
    await db["responses"].create_index(
        [("answers.question_ref.version_id", 1)],
        name="ix_responses_answer_version",
    )


__all__ = ["create_indexes"]

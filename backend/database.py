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


__all__ = ["create_indexes"]

"""HTTP-level tests for the two statistics endpoints using a stub service."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.dependencies import (  # noqa: E402
    get_current_user_id,
    get_stats_service,
)
from backend.stats.router import router  # noqa: E402
from backend.stats.schemas import (  # noqa: E402
    OptionStat,
    Pagination,
    QuestionOverview,
    QuestionStatsDetail,
    SurveyStatsOverview,
    SurveySummary,
    TextAnswerItem,
    VersionSummary,
)
from backend.stats.service import StatsNotFoundError  # noqa: E402

SURVEY_ID = "66f0a1b2c3d4e5f6a7b8c9d0"
VERSION_ID = "66f0a1b2c3d4e5f6a7b8c9d1"
OWNER_ID = ObjectId("651f1c2a9b3e4d5f6a7b8c9d")
NOW = datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)


class StubService:
    def __init__(self) -> None:
        self.last_call: dict | None = None

    async def get_overview(self, survey_id, owner_id) -> SurveyStatsOverview:
        self.last_call = {"method": "overview", "survey_id": survey_id}
        return SurveyStatsOverview(
            survey=SurveySummary(
                id=SURVEY_ID, title="测试问卷", status="published"
            ),
            version=VersionSummary(
                id=VERSION_ID, version_no=1, published_at=NOW
            ),
            response_count=10,
            questions=[
                QuestionOverview(
                    question_id="q_role_0001",
                    type="single_choice",
                    title="身份",
                    required=True,
                    answered_count=10,
                    response_rate=1.0,
                    option_counts=[
                        OptionStat(
                            option_id="o_student_0001",
                            label="学生",
                            count=10,
                            percentage=100.0,
                        )
                    ],
                )
            ],
            generated_at=NOW,
        )

    async def get_question_stats(
        self, survey_id, owner_id, qid, *, page, page_size
    ) -> QuestionStatsDetail:
        self.last_call = {
            "method": "question",
            "survey_id": survey_id,
            "qid": qid,
            "page": page,
            "page_size": page_size,
        }
        return QuestionStatsDetail(
            survey_id=SURVEY_ID,
            survey_version_id=VERSION_ID,
            question_id=qid,
            type="text",
            title="建议",
            required=False,
            answered_count=12,
            answers=[
                TextAnswerItem(text="希望增加案例", submitted_at=NOW)
            ],
            pagination=Pagination(
                page=page,
                page_size=page_size,
                total=12,
                total_pages=3,
            ),
            generated_at=NOW,
        )


class MissingService:
    async def get_overview(self, survey_id, owner_id):
        raise StatsNotFoundError("survey not found")

    async def get_question_stats(self, *args, **kwargs):
        raise AssertionError("not used")


def make_app(service) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: OWNER_ID
    app.dependency_overrides[get_stats_service] = lambda: service
    return app


class StatsApiTests(unittest.TestCase):
    def test_overview_endpoint(self) -> None:
        service = StubService()
        client = TestClient(make_app(service))
        response = client.get(f"/api/surveys/{SURVEY_ID}/stats")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["response_count"], 10)
        self.assertEqual(
            payload["questions"][0]["option_counts"][0]["count"], 10
        )
        # response_model_exclude_none removes number-only fields.
        self.assertNotIn("average", payload["questions"][0])
        self.assertEqual(service.last_call["method"], "overview")

    def test_question_text_endpoint_passes_pagination(self) -> None:
        service = StubService()
        client = TestClient(make_app(service))
        response = client.get(
            f"/api/surveys/{SURVEY_ID}/questions/q_improve_0005/stats",
            params={"page": 2, "page_size": 5},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answers"][0]["text"], "希望增加案例")
        self.assertEqual(payload["pagination"]["page"], 2)
        self.assertEqual(payload["pagination"]["page_size"], 5)
        self.assertEqual(service.last_call["qid"], "q_improve_0005")
        self.assertEqual(service.last_call["page"], 2)
        self.assertEqual(service.last_call["page_size"], 5)

    def test_non_owner_or_missing_survey_maps_to_404(self) -> None:
        client = TestClient(make_app(MissingService()))
        response = client.get(f"/api/surveys/{SURVEY_ID}/stats")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

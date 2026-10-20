"""Unit tests for stats pipeline builders and post-processing."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.stats.pipelines import (  # noqa: E402
    build_choice_question_pipeline,
    build_number_question_pipeline,
    build_overview_pipeline,
    build_text_question_pipeline,
)
from backend.stats.service import (  # noqa: E402
    build_choice_detail_response,
    build_number_detail_response,
    build_overview_response,
    build_text_detail_response,
)

NOW = datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)
SURVEY_ID = ObjectId("66f0a1b2c3d4e5f6a7b8c9d0")
VERSION_ID = ObjectId("66f0a1b2c3d4e5f6a7b8c9d1")


def load_version() -> dict:
    data = json.loads(
        (ROOT / "examples" / "survey_versions.example.json").read_text(
            encoding="utf-8"
        )
    )
    data["_id"] = VERSION_ID
    data["published_at"] = datetime(
        2026, 10, 1, tzinfo=timezone.utc
    )
    return data


def question(version: dict, qid: str) -> dict:
    return next(
        item for item in version["questions"] if item["question_id"] == qid
    )


class PipelineShapeTests(unittest.TestCase):
    def test_overview_uses_single_facet_with_expected_branches(self) -> None:
        pipeline = build_overview_pipeline(SURVEY_ID, VERSION_ID)
        self.assertEqual(pipeline[0]["$match"]["survey_id"], SURVEY_ID)
        self.assertEqual(pipeline[0]["$match"]["survey_version_id"], VERSION_ID)
        facet = pipeline[1]["$facet"]
        self.assertEqual(
            set(facet),
            {
                "response_count",
                "choice_answered",
                "choice_options",
                "number_stats",
                "text_stats",
            },
        )
        self.assertIn("$unwind", facet["choice_options"][0])
        self.assertIn("$group", facet["number_stats"][2])

    def test_choice_detail_unwinds_only_extracted_answer(self) -> None:
        pipeline = build_choice_question_pipeline(
            SURVEY_ID, VERSION_ID, "q_resources_0002", "multi_choice"
        )
        self.assertEqual(
            pipeline[0]["$match"]["answers.question_id"], "q_resources_0002"
        )
        self.assertEqual(pipeline[1]["$set"]["_answer"]["$arrayElemAt"][1], 0)
        self.assertIn("$facet", pipeline[3])
        self.assertIn("$unwind", pipeline[3]["$facet"]["options"][0])
        self.assertEqual(
            pipeline[3]["$facet"]["answered"], [{"$count": "value"}]
        )

    def test_number_detail_uses_group_aggregates(self) -> None:
        pipeline = build_number_question_pipeline(
            SURVEY_ID, VERSION_ID, "q_rating_0004"
        )
        group = pipeline[3]["$facet"]["stats"][0]["$group"]
        self.assertEqual(group["average"], {"$avg": "$_answer.number"})
        self.assertEqual(group["minimum"], {"$min": "$_answer.number"})
        self.assertEqual(group["maximum"], {"$max": "$_answer.number"})

    def test_text_detail_facets_total_and_page(self) -> None:
        pipeline = build_text_question_pipeline(
            SURVEY_ID, VERSION_ID, "q_improve_0005", skip=20, limit=10
        )
        facet = pipeline[-1]["$facet"]
        self.assertEqual(facet["meta"], [{"$count": "value"}])
        self.assertEqual(facet["page"][1], {"$skip": 20})
        self.assertEqual(facet["page"][2], {"$limit": 10})
        self.assertEqual(
            facet["page"][0], {"$sort": {"submitted_at": -1, "_id": -1}}
        )

    def test_text_pagination_inputs_are_checked(self) -> None:
        with self.assertRaises(ValueError):
            build_text_question_pipeline(
                SURVEY_ID, VERSION_ID, "q_improve_0005", skip=-1, limit=10
            )
        with self.assertRaises(ValueError):
            build_text_question_pipeline(
                SURVEY_ID, VERSION_ID, "q_improve_0005", skip=0, limit=0
            )


class MappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.version = load_version()
        self.survey = {
            "_id": SURVEY_ID,
            "title": "数据库课程学习体验调查",
            "status": "published",
        }

    def test_overview_mapping_and_zero_fill(self) -> None:
        raw = {
            "response_count": [{"value": 128}],
            "choice_answered": [
                {"_id": "q_role_0001", "answered_count": 128},
                {"_id": "q_resources_0002", "answered_count": 110},
                {"_id": "q_recommend_0006", "answered_count": 118},
            ],
            "choice_options": [
                {
                    "_id": {
                        "question_id": "q_role_0001",
                        "option_id": "o_student_0001",
                    },
                    "count": 128,
                },
                {
                    "_id": {
                        "question_id": "q_resources_0002",
                        "option_id": "o_lab_0000001",
                    },
                    "count": 45,
                },
            ],
            "number_stats": [
                {
                    "_id": "q_rating_0004",
                    "answered_count": 120,
                    "average": 3.35,
                    "minimum": 1,
                    "maximum": 5,
                }
            ],
            "text_stats": [
                {"_id": "q_nolab_0003", "answered_count": 38},
                {"_id": "q_improve_0005", "answered_count": 64},
            ],
        }
        result = build_overview_response(
            self.survey, self.version, raw, generated_at=NOW
        )
        self.assertEqual(result.response_count, 128)
        self.assertEqual(len(result.questions), 6)

        role = result.questions[0]
        self.assertEqual(role.answered_count, 128)
        self.assertEqual(role.response_rate, 1.0)
        self.assertEqual(
            [(item.count, item.percentage) for item in role.option_counts],
            [(128, 100.0), (0, 0.0)],
        )

        resources = result.questions[1]
        self.assertEqual(resources.answered_count, 110)
        lab = next(
            item
            for item in resources.option_counts
            if item.option_id == "o_lab_0000001"
        )
        self.assertEqual(lab.count, 45)
        self.assertEqual(lab.percentage, 40.91)

        rating = result.questions[3]
        self.assertEqual(rating.answered_count, 120)
        self.assertEqual(rating.average, 3.35)
        self.assertEqual((rating.min, rating.max), (1, 5))

        no_lab = result.questions[2]
        self.assertEqual(no_lab.answered_count, 38)
        self.assertIsNone(no_lab.option_counts)
        self.assertIsNone(no_lab.average)

    def test_choice_detail_mapping_and_zero_fill(self) -> None:
        q = question(self.version, "q_role_0001")
        raw = {
            "answered": [{"value": 128}],
            "options": [{"_id": "o_student_0001", "count": 128}],
        }
        result = build_choice_detail_response(
            survey_id=SURVEY_ID,
            version_id=VERSION_ID,
            question=q,
            raw=raw,
            generated_at=NOW,
        )
        self.assertEqual(result.answered_count, 128)
        self.assertEqual(
            [(item.count, item.percentage) for item in result.option_counts],
            [(128, 100.0), (0, 0.0)],
        )
        self.assertIsNone(result.average)
        self.assertIsNone(result.answers)

    def test_number_detail_mapping(self) -> None:
        q = question(self.version, "q_rating_0004")
        raw = {
            "stats": [
                {
                    "answered_count": 120,
                    "average": 3.35,
                    "minimum": 1,
                    "maximum": 5,
                }
            ]
        }
        result = build_number_detail_response(
            survey_id=SURVEY_ID,
            version_id=VERSION_ID,
            question=q,
            raw=raw,
            generated_at=NOW,
        )
        self.assertEqual(result.answered_count, 120)
        self.assertEqual(result.average, 3.35)
        self.assertEqual((result.min, result.max), (1, 5))
        self.assertIsNone(result.option_counts)

    def test_number_detail_when_no_answers(self) -> None:
        q = question(self.version, "q_rating_0004")
        result = build_number_detail_response(
            survey_id=SURVEY_ID,
            version_id=VERSION_ID,
            question=q,
            raw={"stats": []},
            generated_at=NOW,
        )
        self.assertEqual(result.answered_count, 0)
        self.assertIsNone(result.average)
        self.assertIsNone(result.min)
        self.assertIsNone(result.max)

    def test_text_detail_mapping_and_pagination(self) -> None:
        q = question(self.version, "q_improve_0005")
        raw = {
            "meta": [{"value": 3}],
            "page": [
                {
                    "text": "希望提供更多实验",
                    "submitted_at": datetime(
                        2026, 10, 19, 3, 0, tzinfo=timezone.utc
                    ),
                },
                {
                    "text": "希望增加案例",
                    "submitted_at": datetime(
                        2026, 10, 19, 2, 0, tzinfo=timezone.utc
                    ),
                },
            ],
        }
        result = build_text_detail_response(
            survey_id=SURVEY_ID,
            version_id=VERSION_ID,
            question=q,
            raw=raw,
            page=2,
            page_size=2,
            generated_at=NOW,
        )
        self.assertEqual(result.answered_count, 3)
        self.assertEqual(len(result.answers), 2)
        self.assertEqual(result.pagination.total, 3)
        self.assertEqual(result.pagination.total_pages, 2)
        self.assertEqual(result.answers[0].text, "希望提供更多实验")
        self.assertIsNone(result.average)


if __name__ == "__main__":
    unittest.main()

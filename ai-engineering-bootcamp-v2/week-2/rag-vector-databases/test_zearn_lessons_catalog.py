"""Tests for zearn_lessons.csv catalog query parsing."""

from ingest import zearn_lessons_catalog_document_id_from_query


def test_lesson_catalog_query_parses_grade_and_mission() -> None:
    q = "what are the number and names of the lessons in Grade 2, Mission 5"
    assert zearn_lessons_catalog_document_id_from_query(q) == "zearn_lessons_grade_2_mission_5"


def test_lesson_catalog_query_ignores_unrelated_questions() -> None:
    assert zearn_lessons_catalog_document_id_from_query("How do I add students?") is None


def test_lesson_catalog_query_supports_kindergarten() -> None:
    q = "List the lessons in Kindergarten Mission 1"
    assert zearn_lessons_catalog_document_id_from_query(q) == "zearn_lessons_grade_K_mission_1"

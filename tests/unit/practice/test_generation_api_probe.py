"""The deployed-API probe must catch the bad true/false stem seen in the pilot."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from scripts import verify_practice_generation_api as probe


def _practice_set(prompt: str) -> dict[str, Any]:
    return {
        "id": "set-1",
        "exercises": [
            {
                "id": "exercise-1",
                "ordinal": 0,
                "prompt": prompt,
                "type": "true_false",
                "evidence_citation_ids": ["chunk-1"],
            }
        ],
        "evidence_sources": [{"chunk_id": "chunk-1"}],
    }


def test_api_audit_rejects_interrogative_true_false_and_unresolved_citation() -> None:
    practice_set = _practice_set("当有人问'Where's the pen?'时，正确的回答是什么？")  # noqa: RUF001
    practice_set["exercises"][0]["evidence_citation_ids"] = ["missing"]
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: true_false prompt is not a complete claim",
        "exercise 0: unresolved citation missing",
    ]


def test_api_audit_rejects_readable_structure_with_ocr_garbage() -> None:
    practice_set = _practice_set("POOLE Listen and say. 3% MY §=Here's your cake.")
    practice_set["exercises"][0]["type"] = "short_answer"
    assert probe.audit_practice_set(practice_set, 1) == ["exercise 0: unreadable OCR in prompt"]


def test_api_audit_rejects_merged_dialogue_cloze_from_real_sample() -> None:
    practice_set = _practice_set(
        "补全教材原句\uff1a\u201cA: |s it a monster? A: ____ ' "
        "B: No, it isn't. B: No, it isn't.\u201d"
    )
    practice_set["exercises"][0]["type"] = "fill_in_the_blank"
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: unreadable OCR in prompt",
        "exercise 0: unreadable cloze context",
    ]


def test_api_audit_rejects_broken_punctuation_cloze_from_real_sample() -> None:
    practice_set = _practice_set(
        "补全教材原句\uff1a\u201cOh, ____ cat kite. Your cat or . your kite?\u201d"
    )
    practice_set["exercises"][0]["type"] = "fill_in_the_blank"
    assert probe.audit_practice_set(practice_set, 1) == ["exercise 0: unreadable cloze context"]


def test_api_audit_rejects_page_length_cloze_and_learning_objective_claim() -> None:
    practice_set = _practice_set(
        "补全教材原句\uff1a\u201cHere's your present. Happy birthday, Sam. "
        "Here's your cake. Oh! It's a pen. ____ 1,2, 3. I'm nine!\u201d"
    )
    practice_set["exercises"][0]["type"] = "fill_in_the_blank"
    assert probe.audit_practice_set(practice_set, 1) == ["exercise 0: unreadable cloze context"]
    practice_set["exercises"][0]["type"] = "true_false"
    practice_set["exercises"][0]["prompt"] = "Pen and pencil 是区分词汇的学习目标。"
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: navigation metadata instead of learning content"
    ]


def test_api_audit_rejects_unbound_true_false_reference() -> None:
    practice_set = _practice_set("这句话表明父亲是一名警察。")
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: true_false prompt is not a complete claim"
    ]


def test_api_audit_catches_the_two_misclassified_pilot_exercises() -> None:
    practice_set = _practice_set("根据教材内容，当你向别人介绍父亲时，可能会说：")  # noqa: RUF001
    practice_set["exercises"].append(
        {
            "id": "exercise-2",
            "ordinal": 1,
            "prompt": "当有人递给你蛋糕时，对方可能会说什么?",  # noqa: RUF001
            "type": "fill_in_the_blank",
            "evidence_citation_ids": ["chunk-1"],
        }
    )
    assert probe.audit_practice_set(practice_set, 2) == [
        "exercise 0: true_false prompt is not a complete claim",
        "exercise 1: fill_in_the_blank prompt has no blank",
    ]


def test_api_audit_rejects_unverified_dialogue_pairing() -> None:
    practice_set = _practice_set("有人询问“这是什么?”时, 回答“你好, 猫”的英文表达是什么?")
    practice_set["exercises"][0]["type"] = "multiple_choice"
    assert probe.audit_practice_set(practice_set, 1) == ["exercise 0: unverified dialogue pairing"]


@pytest.mark.parametrize(
    "prompt",
    (
        "'One, two, three, four.' 这句话出现在哪个单元?",
        "'One, two, three, four.' 这句话出现在哪个听力练习环节中?",
        "'One, two, three, four.' 这句话属于哪种活动类型?",
        "'One, two, three, four.' 这个序列出现的单元名称是什么?",
    ),
)
def test_api_audit_rejects_navigation_metadata_questions(prompt: str) -> None:
    practice_set = _practice_set(prompt)
    practice_set["exercises"][0]["type"] = "multiple_choice"
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: navigation metadata instead of learning content"
    ]


def test_api_audit_allows_navigation_as_context() -> None:
    practice_set = _practice_set("在 Listen and say 练习中，Hello 用于问候朋友。")  # noqa: RUF001
    assert probe.audit_practice_set(practice_set, 1) == []


def test_api_audit_rejects_picture_claim_without_image_evidence() -> None:
    practice_set = _practice_set("在图片中，蓝色的物体是一把椅子。")  # noqa: RUF001
    assert probe.audit_practice_set(practice_set, 1) == ["exercise 0: unsupported picture claim"]


def test_api_audit_rejects_multiple_blanks_for_one_answer_input() -> None:
    practice_set = _practice_set("请填写 ____ 和 ____。")
    practice_set["exercises"][0]["type"] = "fill_in_the_blank"
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: fill_in_the_blank has multiple blanks"
    ]


def test_api_audit_rejects_wrong_answer_format_and_pseudo_fill() -> None:
    practice_set = _practice_set("Which expression should be written? ____")
    practice_set["exercises"][0]["type"] = "short_answer"
    practice_set["exercises"].append(
        {
            "id": "exercise-2",
            "ordinal": 1,
            "prompt": "Which expression is used? ____",
            "type": "fill_in_the_blank",
            "evidence_citation_ids": ["chunk-1"],
        }
    )
    assert probe.audit_practice_set(practice_set, 2) == [
        "exercise 0: non-fill prompt contains a blank",
        "exercise 1: open-ended prompt disguised as fill-in",
    ]


def test_api_audit_rejects_repeated_question_with_two_replies() -> None:
    practice_set = _practice_set("当A问“What's this?”时，B是如何回答的？")  # noqa: RUF001
    practice_set["exercises"][0]["type"] = "multiple_choice"
    practice_set["evidence_sources"][0]["text_fragments"] = [
        "A: What's this? B: It's a desk.",
        "A: What's this? B: It's a chair.",
    ]
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: repeated dialogue question without turn"
    ]
    practice_set["exercises"][0]["prompt"] = "当A问'What's this?'时，B是如何回答的？"  # noqa: RUF001
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: repeated dialogue question without turn"
    ]


def test_api_audit_rejects_multiple_supported_point_to_options() -> None:
    practice_set = _practice_set("老师要求学生指向哪个单词？")  # noqa: RUF001
    practice_set["exercises"][0]["type"] = "multiple_choice"
    practice_set["exercises"][0]["options"] = [
        {"id": "a", "text": "hello"},
        {"id": "b", "text": "hi"},
    ]
    practice_set["evidence_sources"][0]["text_excerpt"] = 'Point to "hello"! Point to "hi"!'
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: multiple supported point-to options"
    ]


def test_api_audit_rejects_unstated_injury_scenario() -> None:
    practice_set = _practice_set("如果脚部出现问题，对话中提到的身体部位是____。")  # noqa: RUF001
    practice_set["exercises"][0]["type"] = "fill_in_the_blank"
    practice_set["evidence_sources"][0]["text_excerpt"] = "Point to your foot. Oh no!"
    assert probe.audit_practice_set(practice_set, 1) == ["exercise 0: unsupported injury scenario"]


def test_api_probe_calls_endpoints_and_writes_learner_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []
    responses = [
        {"id": "plan-1"},
        {"id": "job-1", "status": "ready", "practice_set_id": "set-1"},
        _practice_set("课文中的'What's this?'用于询问物品名称。"),
    ]

    def fake_request(
        base_url: str, path: str, token: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        assert base_url == "http://127.0.0.1:28001"
        assert token == "redacted-test-token"
        calls.append((path, body))
        return responses.pop(0)

    monkeypatch.setenv("COURSE_TUTOR_AUTH_TOKEN", "redacted-test-token")
    monkeypatch.setattr(probe, "request_json", fake_request)
    output = tmp_path / "probe.json"
    args = Namespace(
        base_url="http://127.0.0.1:28001",
        book_id="book-1",
        module_id=None,
        count=1,
        difficulty="standard",
        language="zh",
        question_types=None,
        timeout=30,
        output=output,
    )
    assert probe.run(args) == 0
    assert [path for path, _ in calls] == [
        "/catalog/books/book-1/study-plan",
        "/catalog/books/book-1/generations",
        "/sets/set-1",
    ]
    assert calls[1][1] is not None and calls[1][1]["count"] == 1
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["audit_errors"] == []
    assert saved["practice_set"]["exercises"][0]["prompt"].startswith("课文中的")
    assert "redacted-test-token" not in output.read_text(encoding="utf-8")
    assert output.stat().st_mode & 0o777 == 0o600

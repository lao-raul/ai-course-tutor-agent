"""Render a local teacher-only review draft for a fixed Practice candidate.

Protected answers are read from the selected Practice database but never from the
learner API. The output must stay under gitignored ``build/reports`` and is not a
signed golden-gate report.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg


def _review_output(path: Path) -> Path:
    allowed = (Path.cwd() / "build" / "reports").resolve()
    destination = path.resolve()
    if not destination.is_relative_to(allowed):
        raise ValueError("teacher-only review drafts must stay under build/reports")
    return destination


def _answer(exercise: dict[str, Any], protected: dict[str, Any]) -> str:
    question_type = exercise["type"]
    if question_type == "multiple_choice":
        correct = protected["correct_option_id"]
        option = next(item["text"] for item in exercise["options"] if item["id"] == correct)
        return f"{correct}: {option}"
    if question_type == "true_false":
        return "正确" if protected["answer"] else "错误"
    if question_type == "fill_in_the_blank":
        return " / ".join(protected["acceptable_answers"])
    if question_type == "short_answer":
        return protected["exemplar_answer"]
    raise ValueError(f"unknown question type: {question_type}")


def render_review(
    candidate: dict[str, Any], details: list[dict[str, Any]], answers: dict[str, dict[str, Any]]
) -> str:
    lines = [
        "# 教材练习题审阅稿（非验收结论）",
        "",
        f"教材 ID：`{candidate['book_id']}`；内容版本：`{candidate['content_version_id']}`。",
        "本文件含教师专用标准答案和教材片段，请勿发布给学生或提交到 Git。",
        "每题请核对原 PDF 页、答案、表述歧义和与其他题目的语义重复。",
        "",
    ]
    for case, detail in zip(candidate["cases"], details, strict=True):
        if case["generation_id"] != detail["generation"]["id"]:
            raise ValueError("candidate/detail generation mismatch")
        practice_set = detail.get("practice_set") or {}
        exercise = (practice_set.get("exercises") or [{}])[0]
        lines.extend(
            [
                f"## {case['ordinal']}. {case['module_title']}",
                "",
                f"状态：{case['status']}；题型：{case['question_type']}；"
                f"练习 ID：`{case.get('exercise_id') or '无'}`。",
                "",
            ]
        )
        if case["status"] != "ready" or not exercise.get("id"):
            lines.extend([f"失败原因：{detail['generation'].get('error_code')}", ""])
            continue
        lines.extend(["题目：", "", f"> {exercise['prompt']}", ""])
        for option in exercise.get("options", []):
            lines.append(f"- {option['id']}. {option['text']}")
        if exercise.get("options"):
            lines.append("")
        protected = answers.get(exercise["id"])
        if protected is None:
            raise ValueError(f"missing protected answer for {exercise['id']}")
        lines.extend([f"教师标准答案：{_answer(exercise, protected)}", ""])
        cited = set(exercise.get("evidence_citation_ids", []))
        sources = [
            source
            for source in practice_set.get("evidence_sources", [])
            if source["chunk_id"] in cited
        ]
        if len(sources) != len(cited):
            raise ValueError(f"missing cited source for {exercise['id']}")
        for source in sources:
            excerpt = source.get("text_excerpt", "").replace("\n", " ").strip()
            source_label = (
                f"教材：{Path(source['relative_path']).name} · 物理第 {source['anchor_value']} 页"
            )
            lines.extend(
                [
                    source_label,
                    "",
                    f"> {excerpt[:280]}" if excerpt else "> 请查看原 PDF 页。",
                    "",
                ]
            )
        lines.extend(["人工判定：待审核（答案／证据／歧义／重复）", ""])
    return "\n".join(lines)


async def _load_answers(dsn: str, ids: list[UUID]) -> dict[str, dict[str, Any]]:
    connection = await asyncpg.connect(dsn)
    try:
        async with connection.transaction(readonly=True):
            rows = await connection.fetch(
                "SELECT id, protected_answer FROM practice.exercises WHERE id = ANY($1::uuid[])",
                ids,
            )
        return {str(row["id"]): json.loads(row["protected_answer"]) for row in rows}
    finally:
        await connection.close()


def run(args: argparse.Namespace) -> None:
    dsn = os.environ.get("PRACTICE_REVIEW_DSN", "")
    if not dsn:
        raise ValueError("PRACTICE_REVIEW_DSN is required and never saved")
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    details = [
        json.loads(Path(case["detail_report"]).read_text(encoding="utf-8"))
        for case in candidate["cases"]
    ]
    ids = [UUID(case["exercise_id"]) for case in candidate["cases"] if case.get("exercise_id")]
    answers = asyncio.run(_load_answers(dsn, ids))
    output = _review_output(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_review(candidate, details, answers), encoding="utf-8")
    print(f"Teacher-only review draft: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()

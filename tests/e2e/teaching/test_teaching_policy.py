from __future__ import annotations

import uuid

from course_tutor_memory import TeachingPolicy, build_teaching_directive

from course_tutor_api.routes.chat import EvidencePack, _apply_teaching_policy, _build_prompt
from course_tutor_contracts.enums import AnchorType, ChunkClass, EducationLevel
from course_tutor_contracts.retrieval import ChatRequest, RetrievedChunk


def _chunk(chunk_class: ChunkClass) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text=f"material for {chunk_class.value}",
        relative_path="assessment.md",
        mime_type="text/markdown",
        anchor_type=AnchorType.HEADING,
        anchor_value="Question 1",
        chunk_class=chunk_class,
        score=0.9,
    )


def test_assessed_work_progresses_hints_without_premature_solution() -> None:
    question = _chunk(ChunkClass.EXERCISE_QUESTION)
    solution = _chunk(ChunkClass.EXERCISE_SOLUTION)
    assessment = _chunk(ChunkClass.ASSESSMENT)
    pack = EvidencePack(
        candidates=(question, solution, assessment),
        evidence=(question, solution, assessment),
        citation_map={},
        timings_ms={},
    )
    policy = TeachingPolicy(solution_reveal_after_attempts=4)
    hidden = _apply_teaching_policy(
        pack, policy, ChatRequest(query="help", assessment_mode=True, attempt_number=2)
    )
    assert [chunk.chunk_class for chunk in hidden.evidence] == [ChunkClass.EXERCISE_QUESTION]
    directive = build_teaching_directive(policy, assessment_mode=True, attempt_number=2)
    assert "conceptual hint" in directive
    assert "Do not quote, reveal" in directive

    revealed = _apply_teaching_policy(
        pack, policy, ChatRequest(query="help", assessment_mode=True, attempt_number=4)
    )
    assert solution in revealed.evidence


def test_postgraduate_bilingual_policy_is_injected_into_prompt() -> None:
    evidence = (_chunk(ChunkClass.CONTENT),)
    policy = TeachingPolicy(
        education_level=EducationLevel.POSTGRADUATE,
        explanation_style="step_by_step",
        response_language="bilingual",
    )
    directive = build_teaching_directive(policy, assessment_mode=False, attempt_number=1)
    messages = _build_prompt("解释 Bayes rule", evidence, teaching_directive=directive)
    assert "postgraduate" in messages[0].content
    assert "Chinese first" in messages[0].content
    assert "not official instructor guidance" in messages[0].content

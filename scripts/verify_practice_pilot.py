"""Redacted real-PDF/LM-Studio generation pilot without publishing or writing a PracticeSet."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from course_tutor_practice_worker.grounded import GroundedGenerationExecutor
from pypdf import PdfReader

from course_tutor_auth import Principal
from course_tutor_contracts import (
    ChunkClass,
    GeneratePracticeRequest,
    PracticeEvidenceChunk,
    PracticeEvidenceResponse,
    PracticeLanguage,
    QuestionType,
)
from course_tutor_contracts.enums import AccessLabel, AnchorType, UserRole
from course_tutor_practice.adapters.inference import OpenAICompatiblePracticeInference
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.application.generation import GenerationService
from course_tutor_practice.domain import ModuleRecord, StudyPlanRecord


async def run(pdf: Path, page: int, base_url: str, model: str) -> None:
    document = PdfReader(str(pdf))
    if page < 1 or page > len(document.pages):
        raise ValueError("page is outside the PDF")
    text = (document.pages[page - 1].extract_text() or "").strip()
    if len(text) < 150:
        raise ValueError("selected page has insufficient extractable text")

    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="redacted-pilot",
    )
    plan = StudyPlanRecord(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        book_id=uuid4(),
        course_id=uuid4(),
        course_run_id=uuid4(),
        content_version_id=uuid4(),
        name="Redacted Grade 3 pilot",
        revision=1,
        modules=(ModuleRecord(id=uuid4(), ordinal=0, title="Unit 1"),),
    )
    repository = InMemoryPracticeRepository()
    await repository.save_study_plan(plan)
    job, _ = await GenerationService(repository).submit(
        principal,
        plan,
        GeneratePracticeRequest(
            count=1,
            language=PracticeLanguage.ZH,
            question_types=(QuestionType.MULTIPLE_CHOICE,),
            module_id=plan.modules[0].id,
        ),
        "real-pilot",
        "redacted-pilot",
    )
    evidence = PracticeEvidenceResponse(
        generation_id=job.id,
        book_id=job.book_id,
        course_id=job.course_id,
        content_version_id=job.content_version_id,
        retrieval_trace_id=uuid4(),
        retrieval_policy_version="manual-pdf-page-v1",
        allowed_content_classes=(ChunkClass.CONTENT,),
        solution_release_after_incorrect_attempts=3,
        chunks=(
            PracticeEvidenceChunk(
                chunk_id=uuid4(),
                source_id=uuid4(),
                text=text[:3000],
                relative_path="REDACTED.pdf",
                anchor_type=AnchorType.PAGE,
                anchor_value=str(page),
                chunk_class=ChunkClass.CONTENT,
                score=1.0,
            ),
        ),
    )

    class PageEvidence:
        async def retrieve(self, _request, _token, _correlation):  # type: ignore[no-untyped-def]
            return evidence

    inference = OpenAICompatiblePracticeInference(base_url, model, "lm-studio")
    try:
        executor = GroundedGenerationExecutor(PageEvidence(), inference)
        context = await executor.retrieve(job)
        outcome = await executor.generate(job, context)
    finally:
        await inference.aclose()
    print(
        "PASS redacted FLTRP pilot: "
        f"pdf_pages={len(document.pages)} selected_page={page} "
        f"validated_questions={len(outcome.drafts)} "
        f"question_type={outcome.drafts[0].type.value} "
        f"language={outcome.drafts[0].language.value} "
        f"citation_count={len(outcome.drafts[0].evidence_citation_ids)} "
        f"model={outcome.model_version}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--page", type=int, default=11)
    parser.add_argument("--llm-base-url", default="http://192.168.50.146:1234/v1")
    parser.add_argument("--model", default="qwen/qwen3.6-35b-a3b")
    args = parser.parse_args()
    asyncio.run(run(args.pdf, args.page, args.llm_base_url, args.model))

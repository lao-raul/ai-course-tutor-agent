"""Default-plan and idempotent generation command services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from course_tutor_auth import Principal
from course_tutor_auth.practice_delegation import issue_practice_delegation
from course_tutor_contracts import (
    CatalogBookDetail,
    CatalogCourseView,
    GeneratePracticeRequest,
    GenerationStatus,
    PracticeGenerationView,
    StudyPlanModuleView,
    StudyPlanView,
)
from course_tutor_practice.domain import GenerationRecord, ModuleRecord, StudyPlanRecord
from course_tutor_practice.ports import OutlineProvider, PracticeRepository
from course_tutor_shared import get_settings

PLAN_NAMESPACE = uuid.UUID("1df5f2a2-16e5-4f40-b985-46c9a7345bc7")
GENERATION_NAMESPACE = uuid.UUID("75fd5e44-7c05-40c0-af3c-2f2d9305bb03")


def _now() -> datetime:
    return datetime.now(UTC)


def plan_view(plan: StudyPlanRecord) -> StudyPlanView:
    return StudyPlanView(
        id=plan.id,
        book_id=plan.book_id,
        course_id=plan.course_id,
        course_run_id=plan.course_run_id,
        content_version_id=plan.content_version_id,
        name=plan.name,
        revision=plan.revision,
        modules=tuple(
            StudyPlanModuleView(
                id=module.id,
                ordinal=module.ordinal,
                title=module.title,
                outline_node_id=module.outline_node_id,
                objectives=module.objectives,
            )
            for module in plan.modules
        ),
    )


def generation_view(job: GenerationRecord) -> PracticeGenerationView:
    return PracticeGenerationView(
        id=job.id,
        study_plan_id=job.study_plan_id,
        book_id=job.book_id,
        course_id=job.course_id,
        content_version_id=job.content_version_id,
        status=job.status,
        requested_count=job.requested_count,
        practice_set_id=job.practice_set_id,
        error_code=job.error_code,
        retryable=job.retryable,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


class StudyPlanService:
    def __init__(self, repository: PracticeRepository, outline: OutlineProvider) -> None:
        self._repository = repository
        self._outline = outline

    async def ensure_default(
        self,
        principal: Principal,
        book: CatalogBookDetail,
        course: CatalogCourseView,
        bearer: str,
        correlation_id: str | None,
    ) -> StudyPlanRecord:
        existing = await self._repository.get_study_plan(
            principal.tenant_id, book.id, course.content_version_id
        )
        if existing is not None:
            return existing
        outline = await self._outline.get_outline(
            book.id, course.content_version_id, bearer, correlation_id
        )
        plan_id = uuid.uuid5(
            PLAN_NAMESPACE,
            f"{principal.tenant_id}:{book.id}:{course.content_version_id}",
        )
        if outline.availability == "available" and outline.nodes:
            modules = tuple(
                ModuleRecord(
                    id=uuid.uuid5(PLAN_NAMESPACE, f"{plan_id}:{node.id}"),
                    ordinal=index,
                    title=node.title,
                    outline_node_id=node.id,
                )
                for index, node in enumerate(sorted(outline.nodes, key=lambda item: item.ordinal))
            )
        else:
            modules = (
                ModuleRecord(
                    id=uuid.uuid5(PLAN_NAMESPACE, f"{plan_id}:book"),
                    ordinal=0,
                    title=book.title,
                ),
            )
        plan = StudyPlanRecord(
            id=plan_id,
            tenant_id=principal.tenant_id,
            book_id=book.id,
            course_id=course.course_id,
            course_run_id=course.course_run_id,
            content_version_id=course.content_version_id,
            name=f"{book.title} — 默认学习计划",
            revision=1,
            modules=modules,
            policy={"answer_release_after_incorrect_attempts": 3},
        )
        return await self._repository.save_study_plan(plan)


class GenerationService:
    def __init__(
        self, repository: PracticeRepository, delegation_secret: str | None = None
    ) -> None:
        self._repository = repository
        self._delegation_secret = (
            delegation_secret or get_settings().practice_delegation_secret.get_secret_value()
        )

    async def submit(
        self,
        principal: Principal,
        plan: StudyPlanRecord,
        request: GeneratePracticeRequest,
        idempotency_key: str,
        correlation_id: str,
    ) -> tuple[GenerationRecord, bool]:
        if request.study_plan_id is not None and request.study_plan_id != plan.id:
            raise ValueError("study_plan_id does not match the selected book")
        if request.course_id is not None and request.course_id != plan.course_id:
            raise ValueError("course_id does not match the selected book")
        if request.module_id is not None and request.module_id not in {
            module.id for module in plan.modules
        }:
            raise ValueError("module_id does not belong to the selected study plan")
        now = _now()
        generation_id = uuid.uuid5(
            GENERATION_NAMESPACE,
            f"{principal.tenant_id}:{principal.user_id}:{idempotency_key}",
        )
        deadline_at = now + timedelta(minutes=5)
        request_payload = request.model_dump(mode="json")
        request_payload["_delegation_token"] = issue_practice_delegation(
            principal,
            generation_id=generation_id,
            book_id=plan.book_id,
            course_id=plan.course_id,
            content_version_id=plan.content_version_id,
            expires_at=deadline_at,
            secret=self._delegation_secret,
        )
        if request.module_id is not None:
            request_payload["_module_title"] = next(
                module.title for module in plan.modules if module.id == request.module_id
            )
        generation = GenerationRecord(
            id=generation_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            study_plan_id=plan.id,
            module_id=request.module_id,
            book_id=plan.book_id,
            course_id=plan.course_id,
            course_run_id=plan.course_run_id,
            content_version_id=plan.content_version_id,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            requested_count=request.count,
            status=GenerationStatus.QUEUED,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        return await self._repository.submit_generation(generation)

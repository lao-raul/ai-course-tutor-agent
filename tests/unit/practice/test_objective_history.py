"""Accepted objectives are private and scoped to one learner/book/version."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from course_tutor_contracts import (
    GeneratePracticeRequest,
    GenerationStatus,
    PracticeLanguage,
    QuestionType,
)
from course_tutor_practice.generation.errors import GenerationFailure
from course_tutor_practice.generation.objectives import answer_expression_keys
from course_tutor_practice.generation.schemas import GenerationObjective
from tests.unit.practice.test_grounded_generation import _draft, _job


@pytest.mark.asyncio
async def test_cross_job_objectives_are_scoped_and_rechecked_at_commit() -> None:
    repository, queued = await _job(GeneratePracticeRequest(count=1))
    first = replace(queued, status=GenerationStatus.VALIDATING)
    repository.generations[first.id] = first
    draft = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.EN, str(uuid4()))
    prior = GenerationObjective("Respond to a greeting and inquiry about well-being", "answer-key")
    await repository.complete_generation(
        first.id,
        (draft,),
        seed=1,
        prompt_version="test",
        model_version="fake",
        validator_version="test",
        objectives=(prior,),
    )
    second = replace(
        queued,
        id=uuid4(),
        idempotency_key="second",
        status=GenerationStatus.VALIDATING,
    )
    repository.generations[second.id] = second
    assert await repository.list_recent_objectives(second) == (prior,)
    for scoped_elsewhere in (
        replace(second, user_id=uuid4()),
        replace(second, book_id=uuid4()),
        replace(second, content_version_id=uuid4()),
        replace(second, tenant_id=uuid4()),
    ):
        assert await repository.list_recent_objectives(scoped_elsewhere) == ()
    with pytest.raises(GenerationFailure, match="duplicate_objective"):
        await repository.complete_generation(
            second.id,
            (draft,),
            seed=2,
            prompt_version="test",
            model_version="fake",
            validator_version="test",
            objectives=(
                GenerationObjective("Give a polite response when asked how you feel", "answer-key"),
            ),
        )
    assert len(repository.sets) == 1
    with pytest.raises(GenerationFailure, match="duplicate_objective"):
        await repository.complete_generation(
            second.id,
            (draft,),
            seed=2,
            prompt_version="test",
            model_version="fake",
            validator_version="test",
            objectives=(
                GenerationObjective("Respond to a well-being inquiry", "different-answer-key"),
            ),
        )


@pytest.mark.asyncio
async def test_rolling_window_counts_ten_sets_without_deleting_older_history() -> None:
    repository, queued = await _job(GeneratePracticeRequest(count=1))
    original = replace(queued, status=GenerationStatus.VALIDATING)
    repository.generations[original.id] = original
    draft = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.EN, str(uuid4()))
    first = await repository.complete_generation(
        original.id,
        (draft,),
        seed=1,
        prompt_version="test",
        model_version="fake",
        validator_version="test",
        objectives=(GenerationObjective("The oldest objective", "old-key"),),
    )
    for index in range(12):
        practice_set = replace(
            first,
            id=uuid4(),
            generation_id=uuid4(),
            created_at=first.created_at + timedelta(seconds=index + 1),
        )
        repository.sets[practice_set.id] = practice_set
        repository.objective_history[practice_set.id] = (
            GenerationObjective(f"Objective number {index}", f"key-{index}"),
        )
    recent = await repository.list_recent_objectives(original)
    assert len(recent) == 10
    assert recent[0].answer_key == "key-11"
    assert recent[-1].answer_key == "key-2"
    assert len(repository.sets) == 13  # The rolling window does not erase older sets.


@pytest.mark.asyncio
async def test_commit_rejects_cloze_that_reuses_a_longer_answer_phrase() -> None:
    repository, queued = await _job(GeneratePracticeRequest(count=1))
    first = replace(queued, status=GenerationStatus.VALIDATING)
    repository.generations[first.id] = first
    draft = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.EN, str(uuid4()))
    await repository.complete_generation(
        first.id,
        (draft,),
        seed=1,
        prompt_version="test",
        model_version="fake",
        validator_version="test",
        objectives=(
            GenerationObjective(
                "Exchange greetings and state well-being",
                "",
                tuple(answer_expression_keys("I'm fine, thank you.")),
            ),
        ),
    )
    second = replace(queued, id=uuid4(), status=GenerationStatus.VALIDATING)
    repository.generations[second.id] = second
    with pytest.raises(GenerationFailure, match="duplicate_objective"):
        await repository.complete_generation(
            second.id,
            (draft,),
            seed=2,
            prompt_version="test",
            model_version="fake",
            validator_version="test",
            objectives=(
                GenerationObjective(
                    "Respond to a polite inquiry",
                    "",
                    tuple(answer_expression_keys("I'm fine")),
                ),
            ),
        )

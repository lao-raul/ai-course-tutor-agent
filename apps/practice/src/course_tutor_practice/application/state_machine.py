"""Generation state transitions shared by API and workers."""

from course_tutor_contracts import GenerationStatus

ALLOWED_TRANSITIONS: dict[GenerationStatus, frozenset[GenerationStatus]] = {
    GenerationStatus.QUEUED: frozenset(
        {GenerationStatus.RETRIEVING, GenerationStatus.CANCELLED, GenerationStatus.FAILED}
    ),
    GenerationStatus.RETRIEVING: frozenset(
        {
            GenerationStatus.GENERATING,
            GenerationStatus.QUEUED,
            GenerationStatus.CANCELLED,
            GenerationStatus.FAILED,
        }
    ),
    GenerationStatus.GENERATING: frozenset(
        {
            GenerationStatus.VALIDATING,
            GenerationStatus.QUEUED,
            GenerationStatus.CANCELLED,
            GenerationStatus.FAILED,
        }
    ),
    GenerationStatus.VALIDATING: frozenset(
        {
            GenerationStatus.READY,
            GenerationStatus.QUEUED,
            GenerationStatus.CANCELLED,
            GenerationStatus.FAILED,
        }
    ),
    GenerationStatus.READY: frozenset(),
    GenerationStatus.FAILED: frozenset(),
    GenerationStatus.CANCELLED: frozenset(),
}


class InvalidGenerationTransition(ValueError):
    pass


def require_transition(current: GenerationStatus, target: GenerationStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidGenerationTransition(
            f"cannot transition generation from {current} to {target}"
        )

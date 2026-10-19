"""Cross-job novelty must catch close rephrasing without blocking distinct vocabulary."""

from course_tutor_practice.generation.objectives import (
    answer_expression_keys,
    near_duplicate_objective,
    stored_answer_keys,
)
from course_tutor_practice.generation.schemas import GenerationObjective


def test_well_being_reply_rephrasing_is_duplicate() -> None:
    assert near_duplicate_objective(
        "Respond to a greeting and inquiry about well-being",
        "Respond to a well-being inquiry",
    )


def test_different_family_vocabulary_remains_distinct() -> None:
    assert not near_duplicate_objective(
        "Identify father in a family introduction",
        "Identify brother in a family introduction",
    )


def test_self_introduction_alias_catches_different_named_examples() -> None:
    assert near_duplicate_objective(
        "Learning a standard greeting and self-introduction", "Stating one's name"
    )
    assert near_duplicate_objective(
        "Introduce oneself using 'I'm [Name]'",
        "State one's own name",
    )
    assert near_duplicate_objective(
        "Introduce oneself using 'I'm [Name]'",
        "Respond to a name inquiry using 'My name is [Name]'",
    )
    assert not near_duplicate_objective(
        "State one's own name",
        "Request someone's name politely",
    )
    assert near_duplicate_objective(
        "Introducing oneself using 'I'm'",
        "Stating one's name",
    )


def test_counting_sequence_alias_catches_overlapping_ranges() -> None:
    assert near_duplicate_objective(
        "Recite basic English numerals from one to four",
        "Count objects from one to five",
    )
    assert near_duplicate_objective(
        "Recite basic English numerals from one to four",
        "Count objects up to five",
    )
    assert near_duplicate_objective("Counting from one to four", "Counting from one to five")


def test_name_inquiry_alias_catches_different_addressees() -> None:
    assert near_duplicate_objective(
        "Asking for someone's name",
        "Asking a bird its name",
    )
    assert not near_duplicate_objective(
        "Asking for someone's name",
        "Asking for the name of an object",
    )


def test_chinese_near_duplicate_is_detected() -> None:
    assert near_duplicate_objective("如何回答别人问候你好吗", "回答别人问候你好吗")


def test_short_cloze_reply_matches_longer_answer_phrase() -> None:
    assert answer_expression_keys("I'm fine") & answer_expression_keys("I'm fine, thank you.")
    assert answer_expression_keys("Thank you") & answer_expression_keys("I'm fine, thank you.")
    assert answer_expression_keys("I'm fine, thank you.") & answer_expression_keys(
        "I'm fine, thank you. And how are you?"
    )
    assert not answer_expression_keys("This is my father") & answer_expression_keys(
        "This is my brother"
    )


def test_legacy_objective_quote_recovers_expression_without_rewriting_set() -> None:
    legacy = GenerationObjective(
        "Exchange greetings using 'How are you?' and 'I'm fine, thank you.'",
        "legacy-full-hash",
    )
    assert stored_answer_keys(legacy) & answer_expression_keys("I'm fine")

"""Regression coverage for readable textbook evidence labels."""

# The OCR fixture intentionally contains mixed apostrophe glyphs from the textbook.
# ruff: noqa: RUF001

from course_tutor_api.citation_display import display_excerpt


def test_selects_contiguous_dialogue_instead_of_noisy_ocr_edges() -> None:
    raw = (
        "Play the game. Listen and guess. S28 3'¢ Hello! How are you? "
        "I'm fine, thank you. How are you? Hello, I’m Nini. How are you? "
        "I’m fine, thank you. I’m Huanhuan. TT i Lhe TIT TTT TL hee "
        "LTT Tt tL he Dec."
    )
    excerpt = display_excerpt(raw)
    assert excerpt.startswith("How are you? I'm fine, thank you.")
    assert excerpt.endswith("I’m Huanhuan.")
    assert "S28" not in excerpt
    assert "Lhe" not in excerpt
    assert excerpt in raw


def test_does_not_rewrite_clean_chinese_or_math() -> None:
    assert display_excerpt("请观察图形。计算矩阵 A 的行列式。") == (
        "请观察图形。 计算矩阵 A 的行列式。"
    )
    assert display_excerpt("The SVD is A = UΣV^T.") == "The SVD is A = UΣV^T."


def test_returns_empty_when_only_ocr_garbage_is_available() -> None:
    assert display_excerpt("S28 3'¢ Hello! TT i Lhe TIT TTT TL hee LTT.") == ""
    assert display_excerpt("toe ee Wint t Listen, point and say. 23% LOL OD") == ""


def test_bounds_long_clean_excerpt_without_cutting_a_word() -> None:
    excerpt = display_excerpt("Hello, this is a complete textbook sentence. " * 10)
    assert len(excerpt) <= 240
    assert excerpt.endswith("…")

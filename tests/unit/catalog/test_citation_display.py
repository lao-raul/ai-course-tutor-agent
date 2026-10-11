"""Regression coverage for readable textbook evidence labels."""

# The OCR fixture intentionally contains mixed apostrophe glyphs from the textbook.
# ruff: noqa: RUF001

from course_tutor_api.citation_display import display_excerpt, display_fragments


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
    assert display_excerpt("请用 apple 造句。") == "请用 apple 造句。"


def test_returns_empty_when_only_ocr_garbage_is_available() -> None:
    assert display_excerpt("S28 3'¢ Hello! TT i Lhe TIT TTT TL hee LTT.") == ""
    assert display_excerpt("toe ee Wint t Listen, point and say. 23% LOL OD") == ""


def test_scanned_comic_page_quotes_only_verbatim_dialogue() -> None:
    raw = (
        "POOLE Listen and say. 3% MY §=Here's your cake, Sam! Practise. "
        "% SR My Do and say. Here's your Here's your pencil, Lingling! "
        "cap, Sam! it niteasnenaclQ ‘SIDE"
    )
    assert display_excerpt(raw) == "Here's your cake, Sam!"


def test_scanned_family_page_with_reordered_speech_bubbles_has_no_excerpt() -> None:
    raw = (
        "Unit 1. This is my mother. eeeeee#ee#e#08dkeeeeeeee8e 06 © "
        "Listen, point and say. # 3 . {enn ea j= B 3 Here's my father. "
        "\\[_]] Here's my sister. Here's my mother. Here's my brother. "
        '® Listen, point and find "This is..." 2A And she’s my teacher. '
        "e Dee eeeec0@ eee00ee@ »e Seeeeceo®® Seeeceee® Cece5e"
    )
    assert display_excerpt(raw) == ""
    assert display_fragments(raw) == (
        "Here's my sister.",
        "Here's my mother.",
        "Here's my brother.",
    )
    assert all(fragment in raw for fragment in display_fragments(raw))


def test_ambiguous_ocr_does_not_display_a_quote() -> None:
    assert display_excerpt("3% MY §=Sam! % SR My Do and say. cap, Sam!") == ""
    assert display_fragments("3% MY §=Sam! % SR My Do and say. cap, Sam!") == ()


def test_bounds_long_clean_excerpt_without_cutting_a_word() -> None:
    excerpt = display_excerpt("Hello, this is a complete textbook sentence. " * 10)
    assert len(excerpt) <= 240
    assert excerpt.endswith("…")

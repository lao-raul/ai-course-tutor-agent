from course_tutor_ingestion.parsers import _normalize_extracted_text


def test_pdf_text_normalization_canonicalizes_math_and_removes_format_controls() -> None:
    extracted = "Vector \U0001d465\u00a0=\u200b[1, 2]\ufffd"

    assert _normalize_extracted_text(extracted) == "Vector x =[1, 2] "

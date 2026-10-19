"""Small, source-reviewed replacements for demonstrably corrupt PDF OCR pages.

The source PDF stays read-only. A correction applies only to the exact SHA-256
below and is versioned with the ingestion pipeline. Page numbers are physical,
one-based PDF pages, not the printed textbook numbers.
"""

from __future__ import annotations

from course_tutor_ingestion.parsers import Chunk

# Reviewed against the original FLTRP/Chen Lin Grade 3, first-term PDF,
# physical pages 16, 34-36, 40-42, 49-51 and 58 (printed pages 11, 29-31,
# 35-37, 44-46 and 53), on 2026-10-15 and 2026-10-16. Only legible printed
# words are transcribed: exercise
# illustrations do not justify inferred answers or speaker identities. Incomplete
# practice templates such as "It's a..." are omitted as answerless fragments.
_FLTRP_G3_1_SHA256 = "d8e8b67b92a5d615508aa9d950f2be35e3a435a5cdc893d423fc02e7bfb2619b"
_FLTRP_G3_1_PAGES: dict[int, tuple[str, ...]] = {
    16: (
        "Module 2 Unit 2 What's your name?",
        "Listen, point and say.",
        "Your name, please? Sam!",
        "Your name, please? Amy!",
        "Your name, please? Ha ha...",
        "Listen and say.",
        "Good afternoon. I'm Mr Li. Good afternoon, Mr Li.",
        "What's your name? I'm Sam.",
    ),
    34: (
        "Module 5 Unit 2 Nine girls?",
        "Listen, point and say.",
        "How many? One, two, three, four, five. Five!",
        "How many? One, two, three, four, five, six, seven, eight and...?",
        "Listen and say.",
        "How many girls? ... seven, eight, nine! Nine girls? Oh! Ten.",
        "How many boys? ... six, seven, eight, nine, ten, eleven! Eleven boys? Oh! Twelve.",
    ),
    35: (
        "Module 5 Unit 2",
        "Listen and do. Eleven. Nine.",
        "Listen and say. Then sing and do the actions.",
        "Ten little fingers.",
        "One little, two little, three little fingers,",
        "four little, five little, six little fingers,",
        "seven little, eight little, nine little fingers,",
        "ten fingers on my hands.",
    ),
    36: (
        "Module 5 Unit 2",
        "Play the game. Count and answer.",
        "How many dogs? How many cats? How many red caps? How many blue caps?",
        "Make a number poster. Then ask and answer.",
        "How many girls? Six!",
    ),
    40: (
        "Module 6 Unit 2 How old are you?",
        "Listen, point and say.",
        "I'm three. I'm ten. You are three and you are ten?! Yes.",
        "Listen and say.",
        "Hello! Look, I'm nine.",
        "How old are you, Daming? I'm nine too.",
        "Look, I'm nine. Nine? You're six. Oh! I'm nine.",
    ),
    41: (
        "Module 6 Unit 2",
        "Listen and match.",
        "A: How old are you, Maomao? B: I'm seven.",
        "Listen and say. Then sing.",
        "How old are you, Sam? I'm nine. I'm nine.",
        "And how are you, Sam? I'm fine, thank you. I'm fine.",
    ),
    42: (
        "Module 6 Unit 2",
        "Play the game. Look and do.",
        "Stand up, 2, 4, 6 and 10. Stand up, 5 and 8.",
        "Make a birthday card and say.",
        "How old are you? I'm nine. Happy birthday! Thank you!",
    ),
    49: (
        "Module 8 Unit 1 Is it a monster?",
        "Listen, point and say.",
        "Look, my new kite! Your cat or your kite? Oh, it's a cat kite.",
        'Listen, point and find "Is it...?"',
        "Look! What's that? I don't know.",
    ),
    50: (
        "Module 8 Unit 1",
        "Is it a cat? No, it isn't!",
        "Is it a dog? No, it isn't!",
        "Is it a monster? Yes, it is!",
        "Help! Hello! Look. It's a kite.",
    ),
    51: (
        "Module 8 Unit 1",
        "Listen and say.",
        "Is it a kite? No, it isn't.",
        "Is it a cat? Yes, it is.",
        "Practise. Is it a monster? No, it isn't.",
    ),
    58: (
        "Module 9 Unit 2 He's a doctor.",
        "Listen, point and say.",
        "This is my father. He's a policeman. This is my mother. She's a nurse.",
        "Listen and say.",
        "He's a doctor. She's a driver. He's a policeman.",
        "She's a nurse. He's a farmer. She's a teacher.",
    ),
}


def verified_page_chunks(checksum: str, page_count: int) -> dict[int, list[Chunk]]:
    """Return exact-PDF corrections, or nothing for any other edition/content."""
    if checksum != _FLTRP_G3_1_SHA256 or page_count != 83:
        return {}
    return {
        page: [Chunk(text=line, anchor_type="page", anchor_value=str(page)) for line in lines]
        for page, lines in _FLTRP_G3_1_PAGES.items()
    }

"""Gate 18 review items 38-42: `validate_question` - min 1, max 1000 chars, trims only external
whitespace, never collapses internal whitespace, never rejects real Italian/Unicode content.
"""

import pytest

from app.modules.ai.ask_ninfa.errors import InvalidAskQuestionError
from app.modules.ai.ask_ninfa.question import validate_question


def test_38_empty_question_is_invalid() -> None:
    with pytest.raises(InvalidAskQuestionError):
        validate_question("")


def test_39_whitespace_only_question_is_invalid() -> None:
    with pytest.raises(InvalidAskQuestionError):
        validate_question("   \n\t  ")


def test_40_exactly_1000_characters_is_accepted() -> None:
    question = "a" * 1000
    assert validate_question(question) == question


def test_41_over_1000_characters_is_rejected() -> None:
    with pytest.raises(InvalidAskQuestionError):
        validate_question("a" * 1001)


def test_42_unicode_and_italian_content_is_supported() -> None:
    question = "Perché il pickup risulta così basso rispetto all'atteso? È normale? 🏨"
    assert validate_question(question) == question


def test_trims_only_leading_and_trailing_whitespace_never_internal() -> None:
    assert validate_question("  Perché  è successo?  ") == "Perché  è successo?"


def test_a_single_real_character_is_the_minimum_valid_length() -> None:
    assert validate_question("?") == "?"

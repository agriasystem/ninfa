"""Gate 19 review items 26-40: the `output_config.format` JSON Schema shape, and how the adapter
parses (and never blindly trusts) whatever text block a real Anthropic response contains.
"""

import pytest
from anthropic.types import RedactedThinkingBlock, ThinkingBlock

from app.modules.ai.ask_ninfa.types import GroundingRef
from app.modules.ai.gateway.anthropic_provider import _OUTPUT_SCHEMA, _answer_from_message
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelRequest, ModelAnswerStatus
from tests.anthropic_provider_support import (
    FakeMessagesTransport,
    answered_message,
    make_message,
    provider_with_fake_transport,
)

_REQUEST = LanguageModelRequest(
    system_instructions="ISTRUZIONI", context="{}", question="Perché?", max_answer_chars=1200
)


# --- 26: output_config.format is the stable json_schema shape -----------------------------------


def test_26_output_schema_uses_the_stable_json_schema_format() -> None:
    transport = FakeMessagesTransport(response=answered_message())
    provider = provider_with_fake_transport(transport)

    provider.generate(_REQUEST)

    output_config = transport.last_call["output_config"]
    assert output_config["format"]["type"] == "json_schema"
    assert output_config["format"]["schema"] is _OUTPUT_SCHEMA
    assert "effort" in output_config


# --- 27-28: closed statuses/grounding refs in the schema, sourced from Gate 18's own enums -------


def test_27_schema_status_enum_matches_gate18s_model_answer_status_exactly() -> None:
    schema_enum = set(_OUTPUT_SCHEMA["properties"]["status"]["enum"])
    assert schema_enum == {status.value for status in ModelAnswerStatus}


def test_28_schema_grounding_refs_enum_matches_gate18s_grounding_ref_exactly() -> None:
    items_enum = _OUTPUT_SCHEMA["properties"]["grounding_refs"]["items"]["enum"]
    assert set(items_enum) == {ref.value for ref in GroundingRef}


# --- 29: additionalProperties false where supported (verified against the real docs) -------------


def test_29_schema_forbids_additional_properties() -> None:
    assert _OUTPUT_SCHEMA["additionalProperties"] is False


def test_29_schema_never_encodes_business_length_constraints() -> None:
    """`maxLength` etc. are NOT supported by Anthropic Structured Outputs (verified against the
    real docs during this gate's pre-gate check) - business constraints stay Gate 18's own
    `answer_validation.py` job, never duplicated (or silently dropped) here."""
    answer_schema = _OUTPUT_SCHEMA["properties"]["answer"]
    assert "maxLength" not in answer_schema
    assert "minLength" not in answer_schema
    assert "pattern" not in answer_schema


# --- 30-31: both real statuses parse -------------------------------------------------------------


def test_30_answered_parses_into_a_language_model_answer() -> None:
    message = answered_message(answer="Il pickup è sotto le attese.")
    result = _answer_from_message(message)
    assert result.status is ModelAnswerStatus.ANSWERED
    assert result.answer == "Il pickup è sotto le attese."


def test_31_insufficient_context_parses_into_a_language_model_answer() -> None:
    message = make_message(
        {
            "status": "INSUFFICIENT_CONTEXT",
            "answer": "Non posso stabilire un valore esatto con i dati disponibili.",
            "grounding_refs": [],
            "limitations": ["NINFA non include un motore di ottimizzazione del prezzo."],
        }
    )
    result = _answer_from_message(message)
    assert result.status is ModelAnswerStatus.INSUFFICIENT_CONTEXT
    assert result.limitations == ("NINFA non include un motore di ottimizzazione del prezzo.",)


# --- 32-35: malformed/invalid content fails closed at the adapter --------------------------------


def test_32_invalid_status_enum_value_is_rejected() -> None:
    message = make_message(
        {"status": "MAYBE", "answer": "x", "grounding_refs": [], "limitations": []}
    )
    with pytest.raises(LanguageModelUnavailableError):
        _answer_from_message(message)


def test_33_malformed_json_fails_closed() -> None:
    message = make_message({}, text_blocks=["{not valid json"])
    with pytest.raises(LanguageModelUnavailableError):
        _answer_from_message(message)


def test_34_missing_required_field_fails_closed() -> None:
    # "limitations" is deliberately omitted.
    message = make_message({"status": "ANSWERED", "answer": "x", "grounding_refs": []})
    with pytest.raises(LanguageModelUnavailableError):
        _answer_from_message(message)


def test_35_unexpected_extra_field_fails_closed() -> None:
    message = make_message(
        {
            "status": "ANSWERED",
            "answer": "x",
            "grounding_refs": [],
            "limitations": [],
            "confidence_score_override": "99.99",
        }
    )
    with pytest.raises(LanguageModelUnavailableError):
        _answer_from_message(message)


# --- 36-38: text block extraction, thinking ignored and never exposed ----------------------------


def test_36_extracts_the_structured_text_block_among_others() -> None:
    thinking = ThinkingBlock(type="thinking", thinking="internal reasoning", signature="sig")
    message = answered_message(answer="Risposta reale.", extra_blocks=[thinking])
    result = _answer_from_message(message)
    assert result.answer == "Risposta reale."


def test_37_thinking_and_redacted_thinking_blocks_are_ignored() -> None:
    thinking = ThinkingBlock(type="thinking", thinking="secret reasoning process", signature="sig")
    redacted = RedactedThinkingBlock(type="redacted_thinking", data="opaque")
    message = answered_message(answer="Risposta reale.", extra_blocks=[thinking, redacted])
    result = _answer_from_message(message)
    assert "secret reasoning process" not in result.answer
    assert "secret reasoning process" not in str(result)


def test_38_no_thinking_content_is_exposed_anywhere_in_the_parsed_result() -> None:
    thinking = ThinkingBlock(type="thinking", thinking="MUST_NOT_LEAK_THIS", signature="sig")
    message = answered_message(extra_blocks=[thinking])
    result = _answer_from_message(message)
    assert "MUST_NOT_LEAK_THIS" not in result.answer
    assert all("MUST_NOT_LEAK_THIS" not in note for note in result.limitations)


# --- 39-40: missing or ambiguous final text block fails safely -----------------------------------


def test_39_zero_text_blocks_is_unavailable() -> None:
    thinking = ThinkingBlock(type="thinking", thinking="only thinking, no answer", signature="sig")
    message = make_message({}, extra_blocks=[thinking], text_blocks=[])
    with pytest.raises(LanguageModelUnavailableError):
        _answer_from_message(message)


def test_40_more_than_one_text_block_fails_safely_never_guesses_which_one() -> None:
    message = make_message(
        {},
        text_blocks=[
            '{"status": "ANSWERED", "answer": "first", "grounding_refs": [], "limitations": []}',
            '{"status": "ANSWERED", "answer": "second", "grounding_refs": [], "limitations": []}',
        ],
    )
    with pytest.raises(LanguageModelUnavailableError):
        _answer_from_message(message)

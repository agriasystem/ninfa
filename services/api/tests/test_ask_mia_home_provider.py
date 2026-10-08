"""Mia Home through the REAL `AnthropicLanguageModelProvider` (fake transport only): the closed
`grounding_refs` vocabulary travels PER REQUEST, the Decision Ask's own schema object is never
touched, and Mia Home gets exactly the same no-tools / no-web / no-streaming / one-call posture
(ADR 0025) as every other Ask request.
"""

import copy

from app.modules.ai.ask_ninfa.home_types import HomeGroundingRef
from app.modules.ai.ask_ninfa.types import GroundingRef
from app.modules.ai.gateway.anthropic_provider import _OUTPUT_SCHEMA, _output_schema_for
from app.modules.ai.gateway.protocol import LanguageModelRequest
from tests.anthropic_provider_support import (
    FakeMessagesTransport,
    answered_message,
    provider_with_fake_transport,
)

_HOME_VOCABULARY = tuple(ref.value for ref in HomeGroundingRef)

_HOME_REQUEST = LanguageModelRequest(
    system_instructions="ISTRUZIONI",
    context="{}",
    question="Quali dati ha usato NINFA oggi?",
    max_answer_chars=700,
    grounding_ref_values=_HOME_VOCABULARY,
)
_DECISION_REQUEST = LanguageModelRequest(
    system_instructions="ISTRUZIONI", context="{}", question="Perché?", max_answer_chars=700
)


def test_a_default_request_keeps_the_shared_decision_ask_schema_object() -> None:
    assert _output_schema_for(_DECISION_REQUEST) is _OUTPUT_SCHEMA


def test_a_home_request_gets_its_own_vocabulary_without_mutating_the_shared_schema() -> None:
    before = copy.deepcopy(_OUTPUT_SCHEMA)

    schema = _output_schema_for(_HOME_REQUEST)

    assert schema is not _OUTPUT_SCHEMA
    assert schema["properties"]["grounding_refs"]["items"]["enum"] == list(_HOME_VOCABULARY)
    assert before == _OUTPUT_SCHEMA
    assert set(before["properties"]["grounding_refs"]["items"]["enum"]) == {
        ref.value for ref in GroundingRef
    }
    # Everything else about the schema is identical: same statuses, same required keys, closed.
    assert schema["properties"]["status"] == _OUTPUT_SCHEMA["properties"]["status"]
    assert schema["required"] == _OUTPUT_SCHEMA["required"]
    assert schema["additionalProperties"] is False


def test_the_two_vocabularies_are_disjoint() -> None:
    assert not {ref.value for ref in GroundingRef} & set(_HOME_VOCABULARY)


def test_the_provider_sends_the_home_schema_with_no_tools_web_or_streaming() -> None:
    transport = FakeMessagesTransport(response=answered_message())
    provider = provider_with_fake_transport(transport)

    provider.generate(_HOME_REQUEST)

    [call] = transport.calls  # exactly one provider call
    schema = call["output_config"]["format"]["schema"]
    assert schema["properties"]["grounding_refs"]["items"]["enum"] == list(_HOME_VOCABULARY)
    assert "tools" not in call and "tool_choice" not in call
    assert "stream" not in call
    assert "mcp_servers" not in call
    assert call["system"] == "ISTRUZIONI"
    blocks = [block["text"] for block in call["messages"][0]["content"]]
    assert blocks == [
        "<context>\n{}\n</context>",
        "<question>\nQuali dati ha usato NINFA oggi?\n</question>",
    ]


def test_a_default_request_still_sends_the_shared_schema_object() -> None:
    transport = FakeMessagesTransport(response=answered_message())
    provider = provider_with_fake_transport(transport)

    provider.generate(_DECISION_REQUEST)

    assert transport.last_call["output_config"]["format"]["schema"] is _OUTPUT_SCHEMA

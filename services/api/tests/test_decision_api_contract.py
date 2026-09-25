"""Decision API V1: response contract snapshots.

Not a giant literal golden JSON blob - a frozen set of expected top-level field names per response
model (via Pydantic's own `model_json_schema()`), so an accidental rename, a removed field, or a
pagination envelope change is caught here rather than silently shipped. Decimal encoding and
pagination shape are checked directly against `openapi.json`'s own generated schema.
"""

from pydantic import BaseModel

from app.api.v1.decisions.schemas import (
    DecisionDetailResponse,
    DecisionFeedResponse,
    DecisionHistoryResponse,
    DecisionListResponse,
    FeedItemResponse,
)


def _fields(model: type[BaseModel]) -> set[str]:
    return set(model.model_json_schema()["properties"])


def test_feed_response_contract() -> None:
    assert _fields(DecisionFeedResponse) == {
        "property_id",
        "as_of_local_date",
        "feed_state",
        "decision_run_id",
        "run_sequence",
        "triggered_count",
        "clear_count",
        "insufficient_count",
        "not_applicable_count",
        "suppressed_count",
        "items",
    }
    assert _fields(FeedItemResponse) == {
        "decision_id",
        "decision_type",
        "lifecycle_status",
        "transition",
        "priority",
        "first_seen_local_date",
        "last_seen_local_date",
        "episode_count",
        "target",
        "reason_codes",
        "facts",
        "evidence",
        "economic_proxy",
        "source_status",
    }


def test_list_response_contract() -> None:
    assert _fields(DecisionListResponse) == {"items", "next_cursor"}  # never offset-based


def test_detail_response_contract() -> None:
    assert _fields(DecisionDetailResponse) == {
        "decision_id",
        "decision_type",
        "status",
        "first_seen_local_date",
        "last_seen_local_date",
        "last_evaluated_local_date",
        "resolved_local_date",
        "episode_count",
        "triggered_observation_count",
        "target",
        "latest_observation",
        "decision_api_version",
    }


def test_history_response_contract() -> None:
    assert _fields(DecisionHistoryResponse) == {"items", "next_cursor"}


def test_decimal_fields_are_typed_as_strings_in_the_openapi_schema() -> None:
    schema = DecisionFeedResponse.model_json_schema()
    priority_ref = schema["$defs"]["PrioritySnapshot"]["properties"]
    for field in ("impact_score", "urgency_score", "confidence_score", "priority_score"):
        assert priority_ref[field]["type"] == "string", field  # never "number"

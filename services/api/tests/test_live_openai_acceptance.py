"""The live acceptance script, proven against a fake endpoint: its logic is tested even though
the real run needs a key and a network and cannot happen here.

The one thing that must never happen is the script saying PASS when it did not run: with no key it
says NOT RUN and exits 3.
"""

import json
import re
from typing import Any

import httpx2
import pytest

from tests import live_openai_acceptance as live
from tests.openai_support import error, ok
from tests.semantic_support import Behaviour, SemanticStandIn

KEY = "sk-test-not-a-real-key-0000"


def _evidence_of(request: httpx2.Request) -> dict[str, Any]:
    body = json.loads(request.content)
    text = body["input"][0]["content"][0]["text"]
    match = re.search(r"<evidence>\n(.*)\n</evidence>", text, re.DOTALL)
    assert match is not None
    document: dict[str, Any] = json.loads(match.group(1))
    return document


def _endpoint(request: httpx2.Request) -> httpx2.Response:
    """A fake OpenAI: answers like a good reader of the synthetic file, and times out when asked to
    wait an absurdly short time."""
    timeout = request.extensions.get("timeout", {})
    if timeout.get("read") == 0.001:
        raise httpx2.ReadTimeout("too slow", request=request)
    answer = SemanticStandIn(Behaviour.ORACLE, {"Condizione": "status"})._answer(
        _evidence_of(request)
    )
    return ok(answer)


def _transport(handler: Any) -> httpx2.MockTransport:
    return httpx2.MockTransport(handler)


def test_with_no_key_it_says_not_run_and_never_pass(capsys: pytest.CaptureFixture[str]) -> None:
    code = live.main(environ={})

    out = capsys.readouterr().out
    assert code == 3
    assert live.NOT_RUN in out
    assert "PASS" not in out
    assert "OPENAI_API_KEY" in out  # and how to enable it


def test_a_blank_key_is_no_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert live.main(environ={"OPENAI_API_KEY": "   "}) == 3


def test_every_check_passes_against_an_endpoint_that_behaves() -> None:
    report = live.acceptance(KEY, model="gpt-6.1-sol", transport=_transport(_endpoint))

    failed = [c for c in report.checks if not c.passed]
    assert failed == []
    assert report.passed
    names = {c.name for c in report.checks}
    for expected in (
        "responses API endpoint",
        "configured model",
        "store=false",
        "structured output, strict",
        "no tool, state or identifier",
        "no personal value in the request",
        "in SHADOW the answer is exactly the rules' own",
        "a provider that times out leaves the rules' own answer",
    ):
        assert expected in names


def test_the_fixture_really_holds_canary_personal_values() -> None:
    from io import BytesIO

    import openpyxl

    from tests.live_openai_acceptance import CANARIES, fixture

    sheet = openpyxl.load_workbook(BytesIO(fixture())).active
    assert sheet is not None
    cells = {str(c.value) for row in sheet.iter_rows() for c in row}
    assert all(any(canary in cell for cell in cells) for canary in CANARIES[:2])
    assert all(
        canary.endswith(".invalid") or canary.startswith(("Zzyx", "Quirino", "+39 000"))
        for canary in CANARIES
    )


def test_the_real_request_carries_none_of_the_canary_values() -> None:
    seen: list[httpx2.Request] = []

    def recording(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _endpoint(request)

    live.acceptance(KEY, transport=_transport(recording))

    assert seen
    for request in seen:
        text = request.content.decode("utf-8").casefold()
        for canary in live.CANARIES:
            assert canary.casefold() not in text


def test_an_endpoint_that_fails_is_a_failure_not_a_pass() -> None:
    report = live.acceptance(KEY, transport=_transport(lambda _r: error(500)))

    assert not report.passed
    assert any(not c.passed and "closed shape" in c.name for c in report.checks)


def test_the_script_fails_when_the_model_is_not_the_configured_one() -> None:
    def other_model(request: httpx2.Request) -> httpx2.Response:
        return _endpoint(request)

    report = live.acceptance(KEY, model="gpt-6.1-sol", transport=_transport(other_model))
    assert report.passed  # (the control: the same endpoint passes with the right model)

    bad = live.verify_request(
        "/v1/responses", {"model": "something-else", "store": False}, "gpt-6.1-sol"
    )
    assert ("configured model", False, "something-else") in bad


@pytest.mark.parametrize(
    ("body", "failing"),
    [
        ({"model": "m", "store": True}, "store=false"),
        ({"model": "m", "store": False, "tools": []}, "no tool, state or identifier"),
        (
            {"model": "m", "store": False, "previous_response_id": "r"},
            "no tool, state or identifier",
        ),
        ({"model": "m", "store": False, "user": "hotel-1"}, "no tool, state or identifier"),
        (
            {"model": "m", "store": False, "text": {"format": {"type": "json_object"}}},
            "structured output, strict",
        ),
        (
            {"model": "m", "store": False, "input": f"x {live.CANARIES[2]} y"},
            "no personal value in the request",
        ),
    ],
)
def test_the_inspection_of_a_request_catches_every_way_it_could_go_wrong(
    body: dict[str, Any], failing: str
) -> None:
    results = {name: passed for name, passed, _ in live.verify_request("/v1/responses", body, "m")}

    assert results[failing] is False


def test_the_inspection_accepts_a_request_that_is_right() -> None:
    body = {
        "model": "m",
        "store": False,
        "text": {"format": {"type": "json_schema", "strict": True}},
        "input": "nothing personal",
    }

    assert all(passed for _, passed, _ in live.verify_request("/v1/responses", body, "m"))


def test_a_report_prints_no_content() -> None:
    report = live.acceptance(KEY, transport=_transport(_endpoint))

    text = live.render(report, "gpt-6.1-sol")

    assert text.startswith("LIVE OPENAI ACCEPTANCE: PASS")
    for forbidden in ("Condizione", "Confermata", "RES-3000", *live.CANARIES):
        assert forbidden not in text

"""The harness of the LIVE benchmark: no network, no key, no model.

The things that already went wrong once, or that a number rests on: a request two documents share
is asked of the vendor ONCE (the first run asked it twice and got two different answers); a replay
never reaches the network and counts a request it does not know as a miss; a failure replays as the
same failure; every real call is billed in the cost, duplicates included; and without a key the run
says so and does not pretend (exit 3).
"""

import threading
import time
from pathlib import Path

import pytest

from app.modules.ai.import_understanding.resolver import ImportUnderstandingUnavailableError
from app.modules.ai.import_understanding.types import (
    FailureKind,
    ImportUnderstandingRequest,
    ProviderAnswer,
    ProviderUsage,
)
from tests.benchmarks.smart_import_v3 import openai_live
from tests.benchmarks.smart_import_v3.openai_live import Recorded, spend


def request(text: str = "evidence", attempt: int = 1) -> ImportUnderstandingRequest:
    return ImportUnderstandingRequest(
        "instructions", text, {}, attempt=attempt, contract="semantic-v1"
    )


class Vendor:
    """Stands for the real provider: counts its calls, is slow on purpose, and answers differently
    every time (as the real model did for the same request)."""

    contract = "semantic-v1"
    name = "openai"
    model = "test-model"

    def __init__(self, fail: FailureKind | None = None) -> None:
        self.calls = 0
        self.fail = fail
        self._lock = threading.Lock()

    def suggest(self, req: ImportUnderstandingRequest) -> object:
        time.sleep(0.05)
        with self._lock:
            self.calls += 1
            number = self.calls
        usage = ProviderUsage(
            model="test-model", latency_ms=50, input_tokens=1000, output_tokens=100, request_id="r"
        )
        if self.fail is not None:
            raise ImportUnderstandingUnavailableError("down", self.fail, usage)
        return ProviderAnswer({"answer": number}, usage)


def test_a_request_two_documents_share_is_asked_of_the_vendor_once(tmp_path: Path) -> None:
    vendor = Vendor()
    recorded = Recorded(vendor, tmp_path / "recording.jsonl")
    answers: list[object] = []

    def ask() -> None:
        reply = recorded.suggest(request())
        assert isinstance(reply, ProviderAnswer)
        answers.append(reply.payload)

    threads = [threading.Thread(target=ask) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert vendor.calls == 1
    assert len(set(map(str, answers))) == 1  # everyone got the one answer
    assert len(recorded.entries) == 1


def test_a_different_request_is_a_different_call(tmp_path: Path) -> None:
    vendor = Vendor()
    recorded = Recorded(vendor, tmp_path / "recording.jsonl")

    recorded.suggest(request("one"))
    recorded.suggest(request("two"))
    recorded.suggest(request("one", attempt=2))

    assert vendor.calls == 3


def test_a_replay_gives_the_recorded_answer_and_never_reaches_the_vendor(tmp_path: Path) -> None:
    path = tmp_path / "recording.jsonl"
    vendor = Vendor()
    first = Recorded(vendor, path).suggest(request())
    assert isinstance(first, ProviderAnswer)

    replay = Recorded(None, path, frozen=True)
    again = replay.suggest(request())

    assert isinstance(again, ProviderAnswer)
    assert again.payload == first.payload
    assert again.usage.request_id == "r"
    assert vendor.calls == 1 and replay.misses == 0


def test_a_request_that_was_never_recorded_is_a_miss_not_a_call(tmp_path: Path) -> None:
    vendor = Vendor()
    path = tmp_path / "recording.jsonl"
    Recorded(vendor, path).suggest(request("known"))
    replay = Recorded(vendor, path, frozen=True)

    with pytest.raises(ImportUnderstandingUnavailableError):
        replay.suggest(request("unknown"))

    assert replay.misses == 1
    assert vendor.calls == 1  # frozen: the vendor was not asked again


def test_a_failure_replays_as_the_same_failure_and_is_billed(tmp_path: Path) -> None:
    path = tmp_path / "recording.jsonl"
    live = Recorded(Vendor(FailureKind.TIMEOUT), path)
    with pytest.raises(ImportUnderstandingUnavailableError) as first:
        live.suggest(request())
    replay = Recorded(None, path, frozen=True)
    with pytest.raises(ImportUnderstandingUnavailableError) as second:
        replay.suggest(request())

    assert first.value.kind == second.value.kind == FailureKind.TIMEOUT
    assert second.value.usage is not None and second.value.usage.input_tokens == 1000
    assert spend(replay.entries)["calls_failed_by_kind"] == {"TIMEOUT": 1}


def test_the_cost_is_every_real_call_at_the_stated_price(tmp_path: Path) -> None:
    path = tmp_path / "recording.jsonl"
    recorded = Recorded(Vendor(), path)
    recorded.suggest(request("a"))
    recorded.suggest(request("b"))

    spent = spend(recorded.entries)

    assert spent["real_calls"] == 2
    assert spent["tokens_in_total"] == 2000 and spent["tokens_out_total"] == 200
    # 2000 tokens in at $2/M + 200 out at $10/M
    assert spent["cost_usd_at_list_price"] == pytest.approx(0.006)
    assert spent["request_ids_recorded"] == 2


def test_without_a_key_the_run_says_so_and_exits_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(openai_live, "_key_of_the_application", lambda: "")

    code = openai_live.main(["--pilot"])

    assert code == 3
    assert "NOT RUN" in capsys.readouterr().err

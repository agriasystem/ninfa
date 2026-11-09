"""A worker that starts also defers the day's tick (`worker.daily`), once in `--once` mode too: in a
test about something else it must do nothing, and it must not be counted among that test's jobs."""

from typing import Any

import pytest

from worker import daily


@pytest.fixture(autouse=True)
def quiet_daily_tick(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.module.__name__.endswith("test_daily_tick"):
        return

    async def nothing(*_: Any) -> int:
        return 0

    monkeypatch.setattr(daily, "run_daily_tick", nothing)

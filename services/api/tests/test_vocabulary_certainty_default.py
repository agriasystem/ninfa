"""ADR 0052 withdrew the vocabulary certainty; ADR 0054 closes the last way it could still be on
without anyone saying so: the constructor default of `ImportUnderstandingResolver` was `True`, so
any code that built a resolver by hand (the live acceptance, the benchmarks, the replay SHADOW
makes)
ran the withdrawn mechanism unless it remembered to say `False`.

What is pinned here:

* the default of the constructor is OFF, and a resolver built with no word about it is capped;
* with that default, the adversarial files (a sentence of orders in a cell, a sheet name, a title)
  are not READY, and the same files ARE READY when the certainty is switched on explicitly - so the
  check above would fail if the default were ever turned back on;
* the production factory builds it OFF, and ON only from the setting;
* SHADOW's replay applies the reading with the SAME switch as the resolver it replays (it used to
  carry its own, ON), so what SHADOW reports ASSIST would do is what production ASSIST does;
* in the application code nothing constructs a corroborating resolver without saying what the
  certainty is, and the certainty is switched on in no file of the application and in no test file
  that is not in the list below (a deliberate, reviewed place for the withdrawn mechanism).
"""

import ast
import inspect
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.core.config import Settings
from app.core.tenant import TenantContext
from app.modules.ai.gateway.factory import build_import_understanding_resolver
from app.modules.ai.import_understanding.resolver import (
    ImportUnderstandingResolver,
    ReplayResolver,
)
from app.modules.ai.import_understanding.types import AiMode, AiTrace
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from app.modules.data_sources.understanding_types import UnderstandingLevel
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.smart_import_v3.openai_intelligence import _truth, adversarial_docs
from tests.semantic_support import Behaviour, SemanticStandIn, understand_semantic

_API = Path(__file__).resolve().parents[1]
KEY = "sk-proj-REPLACE-ME-with-a-throwaway-test-value-0000"
INJECTION_FILES = (
    "ADV06-injection-in-a-cell",
    "ADV07-injection-in-a-sheet-name",
    "ADV08-injection-in-a-title-header-on-row-4",
)


def settings(**values: object) -> Settings:
    values.setdefault("anthropic_api_key", None)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _stand_in(doc_id: str) -> tuple[Any, bytes]:
    doc = next(d for d in adversarial_docs() if d.id == doc_id)
    return SemanticStandIn(Behaviour.ORACLE, _truth(doc), None, doc.golden.pii_values), doc.content


def _level_with_the_constructor_default(doc_id: str) -> tuple[UnderstandingLevel, int]:
    """The real service, with a resolver built with NO word about the certainty."""
    model, content = _stand_in(doc_id)
    resolver = ImportUnderstandingResolver(model, AiMode.ASSIST, corroborate=True)
    session: Any = None
    tenant = TenantContext(UUID(int=1))
    service = UnderstandingService(session, tenant, SmartImportService(session, tenant), resolver)
    inspection = service.understand(
        DataSourceDomain.BOOKINGS,
        "file.xlsx",
        content,
        UnderstandAnswers(),
        False,
        None,
        False,
        currency="EUR",
    )
    understanding = inspection.understanding
    assert understanding is not None
    assert model.calls >= 1  # the model WAS asked: the difference is not "nothing happened"
    return understanding.level, len(understanding.questions)


# --- the default -----------------------------------------------------------------------------


def test_the_constructor_default_is_no_vocabulary_certainty() -> None:
    parameter = inspect.signature(ImportUnderstandingResolver.__init__).parameters[
        "vocabulary_certainty"
    ]

    assert parameter.default is False
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("mode", [AiMode.OFF, AiMode.SHADOW, AiMode.ASSIST])
def test_a_resolver_built_with_no_word_about_it_is_capped_in_every_mode(mode: AiMode) -> None:
    resolver = ImportUnderstandingResolver(None, mode, corroborate=True)

    assert resolver.vocabulary_certainty is False
    assert resolver.corroborates is False
    assert resolver.wants_certainty is False


@pytest.mark.parametrize("doc_id", INJECTION_FILES)
def test_with_the_default_a_file_with_a_sentence_of_orders_is_not_ready(doc_id: str) -> None:
    level, questions = _level_with_the_constructor_default(doc_id)

    assert level != UnderstandingLevel.READY
    assert questions >= 1


@pytest.mark.parametrize("doc_id", INJECTION_FILES)
def test_the_same_files_are_ready_only_when_the_certainty_is_switched_on_explicitly(
    doc_id: str,
) -> None:
    """The control that makes the test above mean something: the mechanism is still there, and it
    is what turned these files READY (ADR 0052). It is on only because the caller says so."""
    model, content = _stand_in(doc_id)

    inspection = understand_semantic(
        model,
        DataSourceDomain.BOOKINGS,
        content,
        mode=AiMode.ASSIST,
        vocabulary_certainty=True,
    )

    assert inspection.understanding is not None
    assert inspection.understanding.level == UnderstandingLevel.READY


# --- production ------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["shadow", "assist"])
def test_the_production_factory_builds_it_off(mode: str) -> None:
    resolver = build_import_understanding_resolver(
        settings(smart_import_ai_mode=mode, openai_api_key=KEY)
    )

    assert resolver.enabled is True
    assert resolver.vocabulary_certainty is False
    assert resolver.corroborates is False
    assert resolver.wants_certainty is False


@pytest.mark.parametrize("mode", ["off", "shadow", "assist"])
def test_the_production_factory_turns_it_on_only_from_the_setting(mode: str) -> None:
    resolver = build_import_understanding_resolver(
        settings(
            smart_import_ai_mode=mode,
            openai_api_key=KEY,
            smart_import_ai_vocabulary_certainty=True,
        )
    )

    # the setting is read where a model is configured at all (never with the mode off)
    assert resolver.vocabulary_certainty is (mode != "off")


def test_the_live_acceptance_is_built_with_the_flags_production_has() -> None:
    from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider
    from tests.live_openai_acceptance import production_resolver

    built = build_import_understanding_resolver(
        settings(smart_import_ai_mode="assist", openai_api_key=KEY)
    )
    provider = OpenAIImportUnderstandingProvider(KEY, model="a-model", timeout_seconds=1.0)
    traces: list[AiTrace] = []
    acceptance = production_resolver(provider, AiMode.ASSIST, traces.append)

    for name in ("vocabulary_certainty", "corroborates", "wants_certainty", "reads_confirmations"):
        assert getattr(acceptance, name) is getattr(built, name), name


# --- SHADOW's replay -------------------------------------------------------------------------


def test_a_replay_has_to_be_told_the_certainty_it_applies_the_reading_with() -> None:
    resolution: Any = None  # never read: only `resolve` hands it back
    with pytest.raises(TypeError):
        ReplayResolver(resolution)  # type: ignore[call-arg]

    off = ReplayResolver(resolution, vocabulary_certainty=False)
    on = ReplayResolver(resolution, vocabulary_certainty=True)
    assert (off.corroborates, on.corroborates) == (False, True)


@pytest.mark.parametrize("doc_id", INJECTION_FILES)
@pytest.mark.parametrize("certainty", [False, True])
def test_shadow_reports_what_assist_would_do_with_the_same_switch(
    doc_id: str, certainty: bool
) -> None:
    """SHADOW applies nothing; it replays the model's reading through the ASSIST code and reports
    the verdict. With the certainty off that verdict is a question, as production ASSIST gives:
    the replay used to apply it with the certainty ON whatever the resolver said."""
    model, content = _stand_in(doc_id)
    traces: list[AiTrace] = []

    shown = understand_semantic(
        model,
        DataSourceDomain.BOOKINGS,
        content,
        mode=AiMode.SHADOW,
        vocabulary_certainty=certainty,
        observer=traces.append,
    )

    assert shown.understanding is not None
    assert shown.understanding.level != UnderstandingLevel.READY  # SHADOW shows the rules' own
    assert len(traces) == 1
    assert traces[0].level_after == ("READY" if certainty else "ASK")


# --- the code --------------------------------------------------------------------------------


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_in_the_application_builds_a_corroborating_resolver_without_saying_the_certainty() -> (  # noqa: E501
    None
):
    offenders: list[str] = []
    for path in _python_files(_API / "app"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if not isinstance(node, ast.Call):
                continue
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            corroborates = keywords.get("corroborate")
            says_so = isinstance(corroborates, ast.Constant) and corroborates.value is True
            if says_so and "vocabulary_certainty" not in keywords:
                offenders.append(f"{path.relative_to(_API)}:{node.lineno}")

    assert not offenders, offenders


def test_the_application_never_switches_the_certainty_on() -> None:
    on = re.compile(r"vocabulary_certainty\s*[:=]\s*(?:bool\s*=\s*)?True", re.IGNORECASE)

    offenders = [
        str(p.relative_to(_API))
        for p in _python_files(_API / "app")
        if on.search(p.read_text(encoding="utf-8"))
    ]

    assert not offenders, offenders


# The places where the withdrawn mechanism is switched on, each on purpose:
#  - the tests of the mechanism itself (its vocabulary tests, the setting, the recorded
#    `assisted_fields`, the pipeline tests of a model's certain reading, the failures of a model
#    whose reading WOULD be taken as certain);
#  - the scope suites, run against the strongest configuration the layer ever had;
#  - the benchmark that first measured it (`Recording`, openai_intelligence).
# Adding a file here is a review decision, not a convenience.
_MAY_SWITCH_THE_CERTAINTY_ON = frozenset(
    {
        "tests/benchmarks/smart_import_v3/openai_intelligence.py",
        "tests/test_smart_import_ai_config.py",
        "tests/test_smart_import_ai_failures_end_to_end.py",
        "tests/test_smart_import_ai_pipeline.py",
        "tests/test_smart_import_ai_scope.py",
        "tests/test_smart_import_ai_scope_labor.py",
        "tests/test_smart_import_ai_vocabulary_certainty.py",
        "tests/test_smart_import_assisted_fields.py",
        "tests/test_vocabulary_certainty_default.py",
    }
)


def test_the_certainty_is_on_in_no_test_that_does_not_mean_it() -> None:
    on = re.compile(r"vocabulary_certainty\s*[:=]\s*(?:bool\s*=\s*)?True", re.IGNORECASE)

    offenders = sorted(
        str(p.relative_to(_API)).replace("\\", "/")
        for p in _python_files(_API / "tests")
        if on.search(p.read_text(encoding="utf-8"))
        and str(p.relative_to(_API)).replace("\\", "/") not in _MAY_SWITCH_THE_CERTAINTY_ON
    )

    assert not offenders, offenders

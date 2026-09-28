"""Gate 19.1 (ADR 0026, "why leakage fails closed"): a closed, hand-audited output SAFETY check -
the SECOND, independent reason a candidate answer can still fail closed to `AskStatus.UNAVAILABLE`,
after `answer_validation.py`'s own shape/schema checks. This is defense in depth ON TOP OF the
semantic, whitelisted model-facing context Gate 19.1 already built (`semantic_labels.py`,
`context_builder.py`) - the context should never contain a raw internal identifier for the model to
echo in the first place, but this module still checks the model's own free-text OUTPUT too, in case
a provider ever reproduces one anyway (training-data association, a future prompt regression, a
different/future provider with different behaviour).

Runs on every ANSWERED/INSUFFICIENT_CONTEXT candidate BEFORE it ever becomes the public Ask
response. If it ever fires, the response fails closed - never a post-hoc find/replace rewrite of the
model's own text, and never a second provider call to ask it to try again (see ADR 0026, "why no
post-hoc answer rewrite" / "why no second provider call"): a rewritten or a re-generated answer is
no longer a text this module can vouch for having actually checked.
"""

import re

from app.modules.decisions.types import DecisionStatus, LifecycleTransition
from app.modules.decisions.whitelist import EVIDENCE_WHITELIST, FACTS_WHITELIST
from app.modules.intelligence.costs.types import ReasonCode as CostReasonCode
from app.modules.intelligence.distribution.types import ReasonCode as DistributionReasonCode
from app.modules.intelligence.labor.types import ReasonCode as LaborReasonCode
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.intelligence.revenue.types import EvaluationStatus
from app.modules.intelligence.revenue.types import ReasonCode as RevenueReasonCode
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory
from app.modules.recommendations.types import (
    ActionCategory,
    ActionCode,
    ActionScope,
    RecommendationStatus,
    RiskNote,
)

# Every closed, real engine identifier this codebase can ever produce, hand-audited against the
# real enums/whitelists themselves (never re-typed by hand) - so this set can never silently drift
# from what `semantic_labels.py`/`context_builder.py` actually strip out of the model-facing
# context. Checked as a WHOLE WORD (see `contains_technical_leak`), never a substring match.
_KNOWN_TECHNICAL_IDENTIFIERS: frozenset[str] = frozenset(
    {value.value for value in PriorityDecisionType}
    | {value.value for value in DecisionStatus}
    | {value.value for value in LifecycleTransition}
    | {value.value for value in EvaluationStatus}
    | {value.value for value in ActionCode}
    | {value.value for value in ActionCategory}
    | {value.value for value in ActionScope}
    | {value.value for value in RiskNote}
    | {value.value for value in RecommendationStatus}
    | {value.value for value in CostCategory}
    | {value.value for value in LaborCategory}
    | {value.value for value in RevenueReasonCode}
    | {value.value for value in DistributionReasonCode}
    | {value.value for value in CostReasonCode}
    | {value.value for value in LaborReasonCode}
    | {key for keys in FACTS_WHITELIST.values() for key in keys}
    | {key for keys in EVIDENCE_WHITELIST.values() for key in keys}
)

# Italian prose never naturally joins letters/digits with an underscore - this shape is exactly
# (and only) how this codebase's own snake_case fact/evidence keys and TRIGGER_.../REVIEW_.../
# CHECK_... style codes look, so it is a safe, narrow signal even for an identifier not in the
# closed set above (e.g. a future sixth decision type this module was not yet updated for) -
# never a generic word-blocklist that could catch a legitimate Italian word (see this module's own
# docstring: "MA: NON creare regex così generica da bloccare parole italiane legittime").
_SNAKE_CASE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def contains_technical_leak(text: str) -> bool:
    """True if `text` (a candidate answer or limitation) contains a raw internal identifier: an
    exact, whole-word match against this codebase's closed decision/status/action/risk-note/
    category/reason-code/fact-or-evidence-key vocabulary, or any snake_case-shaped token at all."""
    if any(word in _KNOWN_TECHNICAL_IDENTIFIERS for word in _WORD_RE.findall(text)):
        return True
    return bool(_SNAKE_CASE_RE.search(text))


__all__ = ["contains_technical_leak"]

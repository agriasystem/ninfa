"""Gate 19.1 (ADR 0026): `semantic_labels.py` itself - audited against the REAL enums/whitelists it
translates (never re-typed by hand and trusted blindly), and checked for forbidden phrasing per
decision type (OTA brand names, COST/LABOR autonomous-action language).
"""

from app.modules.ai.ask_ninfa import semantic_labels
from app.modules.ai.ask_ninfa.technical_leak import contains_technical_leak
from app.modules.decisions.whitelist import EVIDENCE_WHITELIST, FACTS_WHITELIST
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.recommendations.types import ActionCode


def _all_labels_of(
    mapping: dict[PriorityDecisionType, dict[str, tuple[str, str | None]]],
) -> list[str]:
    return [label for specs in mapping.values() for label, _unit in specs.values()]


_ALL_LABEL_STRINGS: tuple[str, ...] = (
    *semantic_labels.DECISION_TYPE_LABELS.values(),
    *_all_labels_of(semantic_labels.FACT_LABELS),
    *_all_labels_of(semantic_labels.EVIDENCE_LABELS),
)


# --- audit: every mapped fact/evidence key is a REAL whitelisted key ------------------------------


def test_every_fact_label_key_is_a_real_whitelisted_fact_key() -> None:
    for decision_type in PriorityDecisionType:
        mapped_keys = set(semantic_labels.FACT_LABELS[decision_type].keys())
        real_keys = FACTS_WHITELIST[decision_type]
        assert mapped_keys <= real_keys, (decision_type, mapped_keys - real_keys)


def test_every_evidence_label_key_is_a_real_whitelisted_evidence_key() -> None:
    for decision_type in PriorityDecisionType:
        mapped_keys = set(semantic_labels.EVIDENCE_LABELS[decision_type].keys())
        real_keys = EVIDENCE_WHITELIST[decision_type]
        assert mapped_keys <= real_keys, (decision_type, mapped_keys - real_keys)


def test_every_priority_decision_type_has_a_label() -> None:
    for decision_type in PriorityDecisionType:
        assert semantic_labels.decision_label_of(decision_type)


def test_every_action_code_has_a_title() -> None:
    primary_codes = {
        ActionCode.REVIEW_PRICING_AND_AVAILABILITY,
        ActionCode.REVIEW_DEMAND_POSITIONING,
        ActionCode.REVIEW_DISTRIBUTION_MIX,
        ActionCode.REVIEW_COST_DRIVERS,
        ActionCode.REVIEW_STAFFING_PLAN,
    }
    for code in primary_codes:
        assert semantic_labels.primary_action_title_of(code)
        assert semantic_labels.primary_action_description_of(code)
    for code in ActionCode:
        if code not in primary_codes:
            assert semantic_labels.supporting_action_title_of(code)


# --- no label string itself is snake_case / contains a technical suffix ---------------------------


def test_no_mapped_label_is_itself_snake_case_or_technical() -> None:
    for label in _ALL_LABEL_STRINGS:
        assert not contains_technical_leak(label), label


# --- OTA: no invented brand name -----------------------------------------------------------------

_BRAND_NAMES = ("Booking.com", "Airbnb", "Expedia", "Hotels.com", "Vrbo")


def test_ota_labels_never_mention_an_invented_brand_name() -> None:
    ota_labels = [
        label
        for label, _unit in semantic_labels.FACT_LABELS[
            PriorityDecisionType.REV_OTA_DEPENDENCY
        ].values()
    ]
    ota_labels += [
        semantic_labels.primary_action_title_of(ActionCode.REVIEW_DISTRIBUTION_MIX),
        semantic_labels.primary_action_description_of(ActionCode.REVIEW_DISTRIBUTION_MIX),
    ]
    for label in ota_labels:
        for brand in _BRAND_NAMES:
            assert brand not in label


# --- COST/LABOR: never phrased as an executed business action -------------------------------------

_FORBIDDEN_AUTONOMOUS_PHRASES = (
    "cambia fornitore",
    "riduci personale",
    "licenzia",
    "manda a casa",
    "taglia il personale",
)


def test_cost_and_labor_copy_never_reads_as_an_executed_action() -> None:
    texts = [
        semantic_labels.primary_action_title_of(ActionCode.REVIEW_COST_DRIVERS),
        semantic_labels.primary_action_description_of(ActionCode.REVIEW_COST_DRIVERS),
        semantic_labels.primary_action_title_of(ActionCode.REVIEW_STAFFING_PLAN),
        semantic_labels.primary_action_description_of(ActionCode.REVIEW_STAFFING_PLAN),
    ]
    lowered = " ".join(texts).lower()
    for forbidden in _FORBIDDEN_AUTONOMOUS_PHRASES:
        assert forbidden not in lowered

"""Comparing what Smart Import answered with the truth about a document.

The scorer sees two plain things - the golden (read back from JSON) and what was observed - and
nothing of the system's lexicons or rules. Everything it concludes is stated as a `Finding`, in the
categories the benchmark was asked to report:

    DOMAIN_WRONG  SHEET_WRONG  HEADER_WRONG  TABLE_BOUNDARY_WRONG  FIELD_WRONG  FIELD_MISSED
    PII_LEAK  QUESTION_MISSING  QUESTION_UNNECESSARY  FALSE_ZERO_QUESTION  UNSAFE_IMPORT
    EXPECTED_REJECTION  OTHER

The principle behind the weights: a needless question is a small defect of experience, an
automatic import that is wrong is a serious one. "Automatic" means what a person would see as a
summary and one button: level READY, no question, no blocker.

What is judged where
--------------------
* the kind of data, the sheet(s), the header: on the FIRST answer, as a person sees it;
* the table boundary: on the first answer - or, when the truth says a table has to be chosen and
  the system did ask, on the answer after the choice;
* what each column means: on the LAST state of the conversation (a column the person has been
  asked about is not "missed"), while deciding something the document does not say is judged on
  the FIRST answer (it is the system's guess, not the person's);
* the work dates of a day grid: on the dates the importers would actually read.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from tests.benchmarks.smart_import_v3.match import _strip_suffix, header_matches, norm
from tests.benchmarks.smart_import_v3.model import CRITICAL_FIELDS, Golden, Source
from tests.benchmarks.smart_import_v3.observe import Observed, OClaim, OQuestion

# The facts the importers cannot run without, as business facts.
REQUIRED_SCORED: dict[str, frozenset[str]] = {
    "labor": frozenset({"work_date", "department", "planned_hours", "actual_hours"}),
    "bookings": frozenset(
        {"source_record_id", "booked_at", "check_in", "check_out", "channel", "room_revenue"}
    ),
    "costs": frozenset(
        {"supplier_name", "invoice_number", "invoice_date", "line_description", "net_amount"}
    ),
}
# Two spellings of one business fact in the importers.
PSEUDO = {
    "role": "department",
    "labor_category": "department",
    "line_total": "net_amount",
    "invoice_net_amount": "net_amount",
}
FROM_COLUMN = {"COLUMN", "PROFILE", "USER", "ASSISTANT", "LEARNED"}
DOMAIN_OF = {"LABOR": "labor", "BOOKINGS": "bookings", "COSTS": "costs"}

CATEGORIES = (
    "DOMAIN_WRONG",
    "SHEET_WRONG",
    "HEADER_WRONG",
    "TABLE_BOUNDARY_WRONG",
    "FIELD_WRONG",
    "FIELD_MISSED",
    "PII_LEAK",
    "QUESTION_MISSING",
    "QUESTION_UNNECESSARY",
    "FALSE_ZERO_QUESTION",
    "UNSAFE_IMPORT",
    "EXPECTED_REJECTION",
    "OTHER",
)


@dataclass(slots=True)
class Finding:
    category: str
    detail: str
    field: str | None = None
    expected: str = ""
    observed: str = ""
    severity: str = (
        "P3"  # P0 silent wrong data | P1 blocks a valid file | P2 needless friction | P3 edge
    )


@dataclass(slots=True)
class Counters:
    golden: int = 0  # facts the truth says are in the document
    correct: int = 0  # found, in the right place
    wrong: int = 0  # claimed, somewhere else
    missed: int = 0  # not claimed and not asked about
    asked: int = 0  # not claimed, but the person is asked about exactly that column
    claims: int = 0  # claims made on these facts (any level)
    claims_correct: int = 0
    committed: int = 0  # HIGH claims with no question on their column
    committed_correct: int = 0


@dataclass(slots=True)
class CaseResult:
    id: str
    card: str
    filename: str
    tags: list[str]
    outcome: str  # what the truth says V3.0 ought to do
    golden_domain: str
    level: str | None = None
    automatic: bool = False
    warned: bool = False
    fully_correct: bool = False
    false_automation: bool = False
    false_automation_reasons: list[str] = field(default_factory=list)
    observed_domain: str | None = None
    detection_level: str | None = None
    domain_scored: bool = False
    domain_ok: bool = False
    sheet_scored: bool = False
    sheet_ok: bool = False
    header_scored: bool = False
    header_ok: bool = False
    boundary_scored: bool = False
    boundary_ok: bool = False
    period_ok: bool | None = None
    required: Counters = field(default_factory=Counters)
    everything: Counters = field(default_factory=Counters)
    junk_mapped: int = 0
    pii_columns: int = 0
    pii_columns_excluded: int = 0
    pii_values: int = 0
    pii_values_leaked: int = 0
    questions_asked: list[str] = field(default_factory=list)
    questions_expected: list[str] = field(default_factory=list)
    questions_necessary_found: int = 0
    questions_unnecessary: int = 0
    labels_asked_needlessly: int = 0
    labels_guessed_silently: int = 0
    labels_wrong: int = 0
    safe_fallback: bool | None = None  # only for refusals
    strict_fallback: bool | None = None
    rounds: int = 0  # answers the person had to give before the import became automatic
    conversation: bool = False  # the document was not automatic and a conversation was tried
    resolved: bool | None = None  # ...and it ended automatic
    resolved_correct: bool | None = None  # ...and the reading was right
    unresolved_on: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    expected_mapping: dict[str, str] = field(default_factory=dict)
    observed_mapping: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    confidence: str = ""
    egress_calls: int = 0
    egress_leaks: int = 0
    blockers: list[str] = field(default_factory=list)
    totals_state: str | None = None
    amounts_state: str | None = None
    elapsed_ms: float = 0.0
    peak_kib: float | None = None
    error: str | None = None


# --- sources --------------------------------------------------------------------------------------


def _stripped(header: str) -> str:
    return norm(_strip_suffix(header))


def _rank(observed: Observed, header: str) -> int:
    """1 for the first column that carries this header, 2 for the second..."""
    wanted = _stripped(header)
    rank = 0
    for column in observed.columns:
        if _stripped(column.header) == wanted:
            rank += 1
            if column.header == header:
                return rank
    return 1


def _matches(expected: Source, claim: OClaim, observed: Observed) -> bool:
    if expected.kind == "GRID":
        return observed.day_grid
    if expected.kind == "COLUMN":
        return (
            claim.kind in FROM_COLUMN
            and claim.header is not None
            and header_matches(expected.header, claim.header)
            and _rank(observed, claim.header) == expected.occurrence
        )
    return claim.kind == expected.kind


def _describe(source: Source) -> str:
    if source.kind == "COLUMN":
        text = " / ".join(source.header)
        return f"column '{text}'" + (f" #{source.occurrence}" if source.occurrence > 1 else "")
    return source.kind.lower()


def _describe_claim(claim: OClaim) -> str:
    if claim.kind in FROM_COLUMN and claim.header is not None:
        return f"column '{claim.header}' [{claim.level}]"
    return f"{claim.kind.lower()} [{claim.level}]"


def _under_question(claim: OClaim, observed: Observed) -> bool:
    return any(
        q.column is not None and norm(q.column) == norm(claim.header or "\0")
        for q in observed.questions
    )


def _claims(observed: Observed) -> dict[str, list[OClaim]]:
    out: dict[str, list[OClaim]] = defaultdict(list)
    for claim in observed.claims:
        if claim.kind == "PROPERTY":
            continue  # the hotel's own currency
        out[PSEUDO.get(claim.field, claim.field)].append(claim)
    return out


def _names_junk(claim: OClaim, golden: Golden) -> bool:
    if claim.header is None:
        return False
    return any(header_matches(h, claim.header) for h in (*golden.unmapped, *golden.pii_columns))


# --- fields ---------------------------------------------------------------------------------------


def expected_pass(
    result: CaseResult,
    golden: Golden,
    state: Observed,
    expected: dict[str, Source],
) -> tuple[list[Finding], list[str]]:
    """Every fact the truth says is in the document: found, wrong, asked about, or missed."""
    findings: list[Finding] = []
    critical: list[str] = []
    claims = _claims(state)
    required = REQUIRED_SCORED.get(golden.domain, frozenset())
    critical_set = set(CRITICAL_FIELDS.get(golden.domain, ()))
    confirm_asked = any(q.kind == "DEPARTMENT_CONFIRM" for q in state.questions)
    for name, source in expected.items():
        mine = claims.get(name, [])
        hit = next((c for c in mine if _matches(source, c, state)), None)
        counters = [result.everything] + ([result.required] if name in required else [])
        for counter in counters:
            counter.golden += 1
        if hit is not None:
            for counter in counters:
                counter.correct += 1
            continue
        pending = (source.kind == "TITLE" and confirm_asked) or (
            source.kind == "COLUMN"
            and any(
                q.column is not None and header_matches(source.header, q.column)
                for q in state.questions
            )
        )
        if mine:
            for counter in counters:
                counter.wrong += 1
            got = "; ".join(_describe_claim(c) for c in mine)
            findings.append(
                Finding("FIELD_WRONG", f"{name} read from {got}", name, _describe(source), got)
            )
            if name in critical_set:
                critical.append(f"{name} wrong")
        elif pending:
            for counter in counters:
                counter.asked += 1
        else:
            for counter in counters:
                counter.missed += 1
            findings.append(
                Finding(
                    "FIELD_MISSED", f"{name} not recognised", name, _describe(source), "nothing"
                )
            )
            if name in critical_set:
                critical.append(f"{name} missed")
    return findings, critical


def claims_pass(
    result: CaseResult,
    golden: Golden,
    state: Observed,
    expected: dict[str, Source],
    *,
    count: bool,
    report: bool,
) -> tuple[list[Finding], list[str]]:
    """Every claim the system made: right, or a decision about something the document does not
    say (ambiguous), does not hold (absent), or must stay out of the import (junk, personal)."""
    findings: list[Finding] = []
    critical: list[str] = []
    required = REQUIRED_SCORED.get(golden.domain, frozenset())
    critical_set = set(CRITICAL_FIELDS.get(golden.domain, ()))
    for name, mine in _claims(state).items():
        source = expected.get(name)
        for claim in mine:
            correct = source is not None and _matches(source, claim, state)
            committed = claim.level == "HIGH" and not _under_question(claim, state)
            ambiguous = name in golden.ambiguous
            absent = name in golden.absent
            junk = _names_junk(claim, golden)
            if source is None and not (ambiguous or absent or junk):
                continue  # something the truth does not list: neither right nor wrong
            if count:
                for counter in [result.everything] + (
                    [result.required] if name in required else []
                ):
                    counter.claims += 1
                    counter.claims_correct += 1 if correct else 0
                    if committed:
                        counter.committed += 1
                        counter.committed_correct += 1 if correct else 0
            if source is not None or not report:
                continue
            where = _describe_claim(claim)
            if ambiguous and committed:
                findings.append(
                    Finding(
                        "FIELD_WRONG",
                        f"{name} decided without asking ({where}); the document does not say",
                        name,
                        "ask the person",
                        where,
                    )
                )
                if name in critical_set:
                    critical.append(f"{name} guessed")
            elif absent:
                findings.append(
                    Finding(
                        "FIELD_WRONG",
                        f"{name} claimed from {where}, but the document holds no such thing",
                        name,
                        "absent",
                        where,
                    )
                )
                if name in critical_set:
                    critical.append(f"{name} invented")
            elif junk:
                result.junk_mapped += 1
                findings.append(
                    Finding(
                        "FIELD_WRONG",
                        f"{name} claimed from {where}, a column that must stay out of the import",
                        name,
                        "unmapped",
                        where,
                    )
                )
                if name in critical_set:
                    critical.append(f"{name} from a junk column")
    return findings, critical


def _extended(golden: Golden) -> dict[str, Source]:
    """The truth plus what the person's answers establish."""
    expected = dict(golden.fields)
    for spec in golden.answers.get("column_fields", []):
        name = PSEUDO.get(spec["field"], spec["field"])
        expected[name] = Source("COLUMN", tuple(spec["header"]), int(spec.get("occurrence", 1)))
    if "grid_hours" in golden.answers:
        expected[golden.answers["grid_hours"]] = Source("GRID")
    if "period_start" in golden.answers:
        expected["work_date"] = Source("GRID")
    return expected


# --- one case -------------------------------------------------------------------------------------


def _observed_domain(observed: Observed) -> str:
    if observed.detection_domain and observed.detection_level in {"HIGH", "MEDIUM"}:
        return DOMAIN_OF.get(observed.detection_domain, "other")
    return "other"


def _mapping_text(claims: dict[str, list[OClaim]]) -> dict[str, str]:
    return {
        name: "; ".join(_describe_claim(c) for c in mine)
        for name, mine in sorted(claims.items())
        if mine
    }


def _reason(observed: Observed) -> str:
    parts = [f"level {observed.level}"]
    if observed.detection_domain:
        scores = ", ".join(f"{k}={v}" for k, v in observed.detection_scores.items())
        parts.append(f"kind {observed.detection_domain}/{observed.detection_level} ({scores})")
    if observed.claims:
        parts.append(
            "read: "
            + ", ".join(
                f"{c.field}<-{c.header or c.kind.lower()}[{c.level}]" for c in observed.claims
            )
        )
    if observed.questions:
        parts.append(
            "asked: "
            + ", ".join(
                f"{q.kind}{'(' + q.column + ')' if q.column else ''}" for q in observed.questions
            )
        )
    if observed.blockers:
        parts.append("blocked: " + ", ".join(code for code, _ in observed.blockers))
    if observed.error:
        parts.append(f"error: {observed.error}")
    return "; ".join(parts)


def score_case(
    entry: dict[str, Any],
    golden: Golden,
    first: Observed,
    rounds: list[Observed] | None = None,
) -> CaseResult:
    rounds = [r for r in (rounds or []) if r.error is None]
    final = rounds[-1] if rounds else first
    everything = [first, *rounds]
    result = CaseResult(
        id=entry["id"],
        card=entry["card"],
        filename=entry["filename"],
        tags=list(entry["tags"]),
        outcome=golden.outcome,
        golden_domain=golden.domain,
        elapsed_ms=first.elapsed_ms,
        peak_kib=first.peak_kib,
        error=first.error,
        level=first.level,
        automatic=first.automatic,
        blockers=first.blocker_codes,
        totals_state=first.totals_state,
        amounts_state=first.amounts_state,
        rounds=len(rounds),
    )
    result.reason = _reason(first)
    levels = Counter(c.level for c in first.claims if c.kind != "PROPERTY")
    result.confidence = f"kind {first.detection_level or '-'}; fields " + (
        ", ".join(f"{n} {level}" for level, n in sorted(levels.items())) or "none"
    )
    findings = result.findings
    if first.error is not None:
        findings.append(Finding("OTHER", f"Smart Import raised {first.error}", severity="P0"))
        result.expected_mapping = {k: _describe(v) for k, v in golden.fields.items()}
        return result
    automatic = first.automatic
    critical: list[str] = []
    if first.problem is not None and first.level is None:
        findings.append(Finding("OTHER", f"unreadable: {first.problem}", severity="P1"))

    # --- the kind of data (first answer) ---------------------------------------------------------
    result.observed_domain = _observed_domain(first)
    result.detection_level = first.detection_level
    result.domain_scored = golden.data_rows != 0 and first.level is not None
    if result.domain_scored:
        result.domain_ok = result.observed_domain == golden.domain
        if not result.domain_ok:
            findings.append(
                Finding(
                    "DOMAIN_WRONG",
                    f"read as {result.observed_domain} "
                    f"({first.detection_domain}/{first.detection_level})",
                    "domain",
                    golden.domain,
                    result.observed_domain,
                )
            )
            critical.append("domain wrong")

    # --- the table -------------------------------------------------------------------------------
    table_state = first
    if "TABLE" in golden.questions and any(q.kind == "TABLE" for q in first.questions) and rounds:
        table_state = final  # the person has chosen which table
    nonempty = golden.data_rows != 0 and table_state.level is not None
    if golden.sheets and entry["sheets"] >= 2 and nonempty:
        result.sheet_scored = True
        result.sheet_ok = set(table_state.table_sheets) == set(golden.sheets)
        if not result.sheet_ok:
            findings.append(
                Finding(
                    "SHEET_WRONG",
                    "table taken from other sheets",
                    "sheet",
                    ", ".join(golden.sheets),
                    ", ".join(table_state.table_sheets) or "none",
                )
            )
            critical.append("sheet wrong")
    if golden.header_rows and nonempty:
        result.header_scored = True
        result.header_ok = table_state.header_rows == golden.header_rows
        if not result.header_ok:
            findings.append(
                Finding(
                    "HEADER_WRONG",
                    "header found on another row",
                    "header",
                    f"row(s) {list(golden.header_rows)}",
                    f"row(s) {list(table_state.header_rows)}",
                )
            )
            critical.append("header wrong")
    if golden.first_row is not None and golden.data_rows and nonempty:
        result.boundary_scored = True
        problems: list[str] = []
        if table_state.first_row != golden.first_row:
            problems.append(
                f"first record on row {table_state.first_row}, expected {golden.first_row}"
            )
        if table_state.data_rows != golden.data_rows:
            problems.append(
                f"{table_state.data_rows} records read, {golden.data_rows} in the document"
            )
        result.boundary_ok = not problems
        if problems:
            findings.append(
                Finding(
                    "TABLE_BOUNDARY_WRONG",
                    "; ".join(problems),
                    "table",
                    f"row {golden.first_row}, {golden.data_rows} records",
                    f"row {table_state.first_row}, {table_state.data_rows} records",
                )
            )
            critical.append("table boundary wrong")
    if golden.period_start is not None and golden.data_rows != 0:
        dates = final.virtual_dates or first.virtual_dates
        if dates:
            result.period_ok = min(dates) == golden.period_start
            read = f"{min(dates)}..{max(dates)}"
        elif final.period_start is not None:
            result.period_ok = final.period_start == golden.period_start
            read = str(final.period_start)
        else:
            result.period_ok = None
            read = "not established"
        if result.period_ok is False or (
            result.period_ok is None and not _asked(everything, "PERIOD")
        ):
            findings.append(
                Finding(
                    "FIELD_WRONG", "the period of the document", "period", golden.period_start, read
                )
            )
            critical.append("period wrong")

    # --- the meaning -----------------------------------------------------------------------------
    expected = _extended(golden) if rounds else dict(golden.fields)
    if golden.fields or golden.ambiguous or golden.absent or golden.unmapped or rounds:
        found, crit = expected_pass(result, golden, final, expected)
        findings.extend(found)
        critical.extend(crit)
        if final is first:
            found, crit = claims_pass(result, golden, first, expected, count=True, report=True)
            findings.extend(found)
            critical.extend(crit)
        else:
            claims_pass(result, golden, final, expected, count=True, report=False)
            found, crit = claims_pass(
                result, golden, first, dict(golden.fields), count=False, report=True
            )
            findings.extend(found)
            critical.extend(crit)
    if golden.date_order or golden.decimal:
        found, crit = _score_formats(golden, final)
        findings.extend(found)
        critical.extend(crit)
    result.expected_mapping = {k: _describe(v) for k, v in golden.fields.items()}
    result.observed_mapping = _mapping_text(_claims(final))

    # --- personal data ---------------------------------------------------------------------------
    result.pii_columns = len(golden.pii_columns)
    claims = _claims(first)
    for headers in golden.pii_columns:
        mapped = [
            c.field
            for c in first.columns
            if header_matches(headers, c.header) and c.field is not None
        ]
        used = [
            c
            for mine in claims.values()
            for c in mine
            if c.header and header_matches(headers, c.header)
        ]
        if mapped or used:
            findings.append(
                Finding(
                    "PII_LEAK",
                    f"personal column '{headers[-1]}' became {', '.join(mapped) or 'a field'}",
                    "pii",
                    "left out",
                    ", ".join(mapped) or "mapped",
                    severity="P0",
                )
            )
        else:
            result.pii_columns_excluded += 1
    payload = " ".join(state.payload for state in everything).casefold()
    leaked = [v for v in golden.pii_values if v.casefold() in payload]
    result.pii_values = len(golden.pii_values)
    result.pii_values_leaked = len(leaked)
    if leaked:
        findings.append(
            Finding(
                "PII_LEAK",
                f"{len(leaked)} personal values are in the answer sent to the browser",
                "pii",
                "none",
                f"{len(leaked)} values",
                severity="P0",
            )
        )

    # --- department words, then questions ------------------------------------------------------
    critical.extend(_score_labels(result, golden, first, everything))
    _score_questions(result, golden, everything)

    # --- the decision ----------------------------------------------------------------------------
    warning = first.totals_state == "MISMATCH" or first.amounts_state == "MISMATCH"
    result.warned = automatic and warning
    if automatic and golden.outcome == "WARN" and warning:
        pass  # going on is acceptable: the contradiction is shown as a warning
    elif automatic and golden.outcome != "READY":
        category = "FALSE_ZERO_QUESTION" if golden.outcome == "ASK" else "UNSAFE_IMPORT"
        needs = {
            "REJECT": "must be refused",
            "NOT_AUTOMATIC": "needs a person",
            "WARN": "contradicts itself and the contradiction is not shown",
            "ASK": "needs " + ", ".join(golden.questions),
        }[golden.outcome]
        findings.append(
            Finding(
                category,
                f"offered as automatic, but the document {needs}",
                "decision",
                golden.outcome,
                "READY",
            )
        )
        critical.append(f"automatic where {golden.outcome} expected")
    if golden.outcome in {"REJECT", "NOT_AUTOMATIC", "WARN"}:
        result.safe_fallback = (not automatic) or (golden.outcome == "WARN" and result.warned)
        result.strict_fallback = first.level in {"MANUAL", "BLOCKED"}
        if golden.outcome == "REJECT" and not automatic and first.level == "ASK":
            findings.append(
                Finding(
                    "EXPECTED_REJECTION",
                    "asked questions about a document V3.0 cannot import",
                    "decision",
                    "refusal",
                    "ASK",
                )
            )
    if golden.outcome == "ASK":
        asked_kinds = {q.kind for state in everything for q in state.questions}
        for kind in golden.questions:
            if kind not in asked_kinds:
                findings.append(
                    Finding(
                        "QUESTION_MISSING",
                        f"{kind} was not asked ({first.level})",
                        "question",
                        kind,
                        ", ".join(first.question_kinds) or first.level or "none",
                    )
                )
    if (
        golden.outcome == "READY"
        and first.level in {"MANUAL", "BLOCKED"}
        and not any(f.category in {"FIELD_MISSED", "FIELD_WRONG"} for f in findings)
    ):
        findings.append(
            Finding(
                "OTHER",
                f"a valid document ended as {first.level} ({', '.join(first.blocker_codes)})",
                "decision",
                "READY",
                first.level or "",
            )
        )

    if automatic:
        result.false_automation = bool(critical)
        result.false_automation_reasons = sorted(set(critical))
        if critical and not any(
            f.category in {"FALSE_ZERO_QUESTION", "UNSAFE_IMPORT"} for f in findings
        ):
            findings.append(
                Finding(
                    "FALSE_ZERO_QUESTION",
                    "offered as automatic with: " + "; ".join(sorted(set(critical))),
                    "decision",
                    "correct reading",
                    "; ".join(sorted(set(critical))),
                )
            )
    bad = [f for f in findings if f.category not in {"QUESTION_UNNECESSARY", "EXPECTED_REJECTION"}]
    result.fully_correct = (
        automatic
        and golden.outcome in {"READY", "WARN"}
        and not bad
        and (golden.outcome == "READY" or result.warned)
    )
    # --- the conversation ------------------------------------------------------------------------
    result.conversation = bool(rounds)
    if rounds:
        result.resolved = final.automatic
        scratch = CaseResult(
            result.id, result.card, result.filename, [], golden.outcome, golden.domain
        )
        wrong, crit = expected_pass(scratch, golden, final, expected)
        boundary_ok = True
        if golden.first_row is not None and golden.data_rows:
            boundary_ok = (
                final.first_row == golden.first_row and final.data_rows == golden.data_rows
            )
        result.resolved_correct = bool(
            final.automatic
            and not crit
            and boundary_ok
            and not any(f.category == "FIELD_WRONG" for f in wrong)
        )
    if not first.automatic:
        result.unresolved_on = [q.kind for q in final.questions] if not final.automatic else []
    for finding in findings:
        finding.severity = (
            finding.severity if finding.category == "PII_LEAK" else _severity(finding, result)
        )
    return result


def _order_of(pattern: str) -> str:
    """DMY / MDY / YMD from a strptime pattern such as %d/%m/%Y."""
    letters = [c for c in pattern.replace("%", "") if c in "dmY"]
    return "".join(letters[:3]).upper()


def _score_formats(golden: Golden, state: Observed) -> tuple[list[Finding], list[str]]:
    """How the text dates and amounts are read, when the truth knows how they are written. Not
    resolving them yet (a question is open) is not an error; resolving them the other way is."""
    findings: list[Finding] = []
    critical: list[str] = []
    if golden.date_order:
        orders = {_order_of(p) for p in state.date_patterns.values()}
        if orders and orders != {golden.date_order}:
            read = "/".join(sorted(orders))
            findings.append(
                Finding(
                    "FIELD_WRONG",
                    f"text dates written {golden.date_order} are read as {read}",
                    "date format",
                    golden.date_order,
                    read,
                )
            )
            critical.append("dates misread")
    if golden.decimal and state.decimal_mark is not None and state.decimal_mark != golden.decimal:
        findings.append(
            Finding(
                "FIELD_WRONG",
                f"amounts written with '{golden.decimal}' as decimal mark are read with "
                f"'{state.decimal_mark}'",
                "amount format",
                golden.decimal,
                state.decimal_mark,
            )
        )
        critical.append("amounts misread")
    return findings, critical


def _asked(states: list[Observed], kind: str) -> bool:
    return any(q.kind == kind for state in states for q in state.questions)


def _distinct_questions(states: list[Observed]) -> list[OQuestion]:
    seen: set[tuple[Any, ...]] = set()
    out: list[OQuestion] = []
    for state in states:
        for q in state.questions:
            key = (q.kind, q.column, q.document, q.labels)
            if key not in seen:
                seen.add(key)
                out.append(q)
    return out


def _score_labels(
    result: CaseResult, golden: Golden, first: Observed, states: list[Observed]
) -> list[str]:
    from app.modules.data_sources.understanding_labor import category_of

    critical: list[str] = []
    asked: dict[str, set[str]] = defaultdict(set)
    for q in _distinct_questions(states):
        if q.kind == "VALUE_LABELS":
            asked[q.document or "role_mapping"].update(norm(label) for label in q.labels)
    department_from_column = any(
        c.kind in FROM_COLUMN for c in _claims(first).get("department", [])
    ) or any(q.kind == "VALUE_LABELS" and q.document == "role_mapping" for q in first.questions)
    for document, truths in golden.labels.items():
        for label, truth in truths.items():
            key = norm(label)
            was_asked = key in asked.get(document, set())
            if truth == "?":
                if not was_asked and first.level in {"READY", "ASK"}:
                    result.labels_guessed_silently += 1
                    result.findings.append(
                        Finding(
                            "FIELD_WRONG",
                            f"'{label}' ({document}) was not asked about, "
                            "yet the document does not say",
                            f"label:{label}",
                            "ask the person",
                            "decided silently",
                        )
                    )
                    critical.append(f"label {label} guessed")
                continue
            if was_asked:
                result.labels_asked_needlessly += 1
                continue
            if document == "role_mapping" and department_from_column:
                got = category_of(label, {})
                if got is not None and got != truth:
                    result.labels_wrong += 1
                    result.findings.append(
                        Finding(
                            "FIELD_WRONG",
                            f"department word '{label}' becomes {got}",
                            f"label:{label}",
                            truth,
                            got,
                        )
                    )
                    critical.append(f"department word {label} wrong")
            elif document == "category_mapping":
                got_map = first.labels.get("category_mapping", {})
                found = next((v for k, v in got_map.items() if norm(k) == key), None)
                if found is not None and found != truth:
                    result.labels_wrong += 1
                    result.findings.append(
                        Finding(
                            "FIELD_WRONG",
                            f"category word '{label}' becomes {found}",
                            f"label:{label}",
                            truth,
                            found,
                        )
                    )
    return critical


def _score_questions(result: CaseResult, golden: Golden, states: list[Observed]) -> None:
    expected = list(golden.questions)
    tolerated = set(golden.tolerated)
    distinct = _distinct_questions(states)
    kinds = [q.kind for q in distinct]
    result.questions_asked = kinds
    result.questions_expected = expected
    result.questions_necessary_found = sum(1 for kind in expected if kind in kinds)
    for q in distinct:
        if q.kind in expected or q.kind in tolerated:
            continue
        result.questions_unnecessary += 1
        result.findings.append(
            Finding(
                "QUESTION_UNNECESSARY",
                f"{q.kind}{' on ' + repr(q.column) if q.column else ''}"
                + (f" about {', '.join(q.labels)}" if q.labels else "")
                + " could have been avoided",
                "question",
                "none",
                q.kind + (f" ({q.column})" if q.column else ""),
            )
        )


def _severity(finding: Finding, result: CaseResult) -> str:
    automatic = result.automatic
    category = finding.category
    if category in {"PII_LEAK", "FALSE_ZERO_QUESTION", "UNSAFE_IMPORT"}:
        return "P0"
    if category == "OTHER" and result.error:
        return "P0"
    if category == "TABLE_BOUNDARY_WRONG" and result.level != "BLOCKED":
        return (
            "P0"  # records dropped or foreign lines imported, whatever the screen the person sees
        )
    if category in {
        "FIELD_WRONG",
        "DOMAIN_WRONG",
        "HEADER_WRONG",
        "TABLE_BOUNDARY_WRONG",
        "SHEET_WRONG",
    }:
        if automatic:
            return "P0"
        if result.level in {"READY", "ASK"} and category != "DOMAIN_WRONG":
            return "P1"
        return "P1" if result.outcome in {"READY", "ASK"} else "P2"
    if category == "FIELD_MISSED":
        if result.outcome in {"READY", "ASK"} and result.level in {"MANUAL", "BLOCKED"}:
            return "P1"
        return "P2"
    if category == "QUESTION_MISSING":
        return "P1" if result.level in {"MANUAL", "BLOCKED"} and result.outcome == "ASK" else "P3"
    if category == "OTHER":
        return "P1"
    if category in {"QUESTION_UNNECESSARY", "EXPECTED_REJECTION"}:
        return "P2"
    return "P3"

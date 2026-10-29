"""Universal Understanding 2.1 - the review of the questions the scorer calls "unnecessary".

The scorer counts a question as unnecessary when its KIND is neither required nor tolerated by the
golden of the document. The goldens of this corpus were written before several product decisions
(hardening 1 and 2, question reduction 1), and in a few places they say "obvious" where the product
deliberately asks. This file lists, case by case, the questions that stay asked ON PURPOSE, why, and
where the decision is pinned (a document of an earlier gate and a test that fails if the behaviour
changes). `apply_review` turns each into a TOLERATED kind of that document's golden - nothing else
about the golden changes - so the number of unnecessary questions the benchmark reports is the
number of questions nobody can justify.

Nothing here hides a question that could be avoided: the cases whose information IS in the file
(`LO07`, `CO04`, `BO09`'s `Stato`) were fixed in the engine and have no entry. A case that is a real
gap (`L62`) has no entry either: it stays counted.

Classes
  HUMAN_REQUIRED   the meaning is not provable from the file; the person decides
  SAFETY_REQUIRED  the question protects from a false automation or from a contradiction
"""

from dataclasses import dataclass

from tests.benchmarks.smart_import_v3.model import Doc

HUMAN_REQUIRED = "HUMAN_REQUIRED"
SAFETY_REQUIRED = "SAFETY_REQUIRED"

QR1 = "docs/benchmarks/smart-import-v3-question-reduction-1.md"
H1 = "docs/benchmarks/smart-import-v3-hardening-1.md"
H2 = "docs/benchmarks/smart-import-v3-hardening-2.md"

QR_TESTS = "test_smart_import_question_reduction.py::"
T_CODES = QR_TESTS + "test_a_code_or_a_word_that_could_be_two_departments_is_still_asked"
T_LONE_TOTAL = QR_TESTS + "test_a_lone_total_is_still_one_confirmation"
T_LOOK_ALIKE = QR_TESTS + "test_two_columns_that_say_the_same_thing_are_still_a_choice"
T_LOOSE_NAMES = (
    "test_smart_import_hardening.py::"
    "test_the_holder_and_the_hand_made_headings_are_read_as_what_they_are"
)
T_REVERSED = (
    "test_smart_import_hardening_2.py::"
    "test_an_arrival_after_the_departure_on_every_row_is_asked_about_and_nothing_is_swapped"
)


@dataclass(frozen=True, slots=True)
class Review:
    kind: str  # the question kind that stays asked
    klass: str
    why: str
    pinned_by: tuple[str, ...]  # documents of earlier gates that decided it
    tests: tuple[str, ...] = ()  # "file::test" that must exist and pins the behaviour


def _codes(why: str) -> Review:
    return Review("VALUE_LABELS", HUMAN_REQUIRED, why, (QR1,), (T_CODES,))


def _bare_amount(why: str) -> Review:
    return Review("COLUMN_MEANING", HUMAN_REQUIRED, why, (QR1, H2), (T_LONE_TOTAL,))


def _reversed() -> Review:
    return Review(
        "DATES_REVERSED",
        SAFETY_REQUIRED,
        "arrival after departure on every row: the headers contradict the values and NINFA "
        "never swaps them silently",
        (QR1, H2),
        (T_REVERSED,),
    )


REVIEWS: dict[str, tuple[Review, ...]] = {
    # --- amounts that do not say what they hold (money is never decided by a word) ---------------
    "B14": (_bare_amount("`Price` alone: a night's rate or the stay's room revenue"),),
    "B41": (_bare_amount("a lone `Total`: whether it holds extras and taxes is written nowhere"),),
    "B42": (_bare_amount("`Ricavo` alone: the room revenue or the whole stay"),),
    "BO01": (
        _bare_amount("`Imp.` alone: imponibile, importo or imposta - three different amounts"),
    ),
    "BO03": (_bare_amount("`Tot` alone: the total of the stay, not the room revenue"),),
    # --- codes and abbreviations are the hotel's own ---------------------------------------------
    "L36": (_codes("`FO`, `HK`, `HSKP`, `REC`: hotel codes - `REC` is Reception or Receiving"),),
    "LO15": (_codes("`FO`, `HK`, `REC`, as above"),),
    "BO09": (
        _codes("`OK`, `CANC`, `NS` are the hotel's status codes; a cancelled stay changes results"),
    ),
    # --- two columns that say the same thing: a real choice --------------------------------
    "B64": (
        Review(
            "COLUMN_MEANING",
            HUMAN_REQUIRED,
            "`Check-in` and `Check-in effettivo` side by side: which is the arrival is a choice",
            (QR1, H1),
            (T_LOOK_ALIKE,),
        ),
    ),
    # --- informal headers whose values cannot prove them ------------------------------------
    "C46": (
        Review(
            "COLUMN_MEANING",
            HUMAN_REQUIRED,
            "`Da chi` / `Cosa`: two loose names are confirmed once, not trusted",
            (QR1,),
            (T_LOOSE_NAMES,),
        ),
    ),
    # --- contradictions ---------------------------------------------------------------------------
    "B50": (_reversed(),),
    "B55": (_reversed(),),
    "B51": (
        Review(
            "DOMAIN",
            SAFETY_REQUIRED,
            "an occupancy calendar that the detector reads as staff: contrary evidence, so the "
            "card is argued with",
            (QR1,),
        ),
    ),
}


def apply_review(docs: list[Doc]) -> None:
    """Tolerates, in the golden of each reviewed document, the kinds of question that stay asked."""
    by_prefix = {doc.id.split("_", 1)[0]: doc for doc in docs}
    unknown = sorted(set(REVIEWS) - set(by_prefix))
    if unknown:
        raise ValueError(f"reviewed documents that do not exist: {unknown}")
    for prefix, reviews in REVIEWS.items():
        golden = by_prefix[prefix].golden
        golden.tolerated = tuple(dict.fromkeys((*golden.tolerated, *(r.kind for r in reviews))))

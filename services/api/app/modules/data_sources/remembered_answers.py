"""What a source remembers from a person's answers, and the way to correct it without help.

    an answer is learned -> the next file does not ask -> the answer was wrong -> the person
    corrects it or makes NINFA forget it -> the next file uses the new answer, or asks again

Two things are shown, because two things are remembered:

* WORDS: "Stato «modificata» means Non presentato". A word belongs to the SOURCE (the profile's
  `status_mapping`, `role_mapping`, `category_mapping`, `channel_mapping`), so it counts for all its
  families. It can be corrected, within the closed list the question offered, or forgotten.
  Forgotten, a word the engine does not know is asked about again; one it knows goes back to the
  engine's meaning.
* FILES: one recurring kind of file a person confirmed (a `source_learning.Memory`): its columns,
  the formats and what it holds. It can only be forgotten, whole and alone: the next such file is
  read like one nobody taught, and the other families stay exactly as they are.

What is not here: the matching of the columns, which has its own way ("Modifica associazioni",
"Dimentica configurazione"), and a family only the engine read, which has decided nothing.

NOTHING RETROACTIVE: this touches the profile and nothing else. Every booking, shift and document
already imported stays as it was read; a correction counts from the next import. NO HEURISTIC: a
word never changes meaning by itself.

Each change leaves a line in `Learning.corrections`, next to what it changed: when, what, from what
to what, and who. The row itself says which source, property and workspace. Like everything else in
that section it holds no value of a file: a word is named by its handle, never written out, and a
meaning is kept only when it comes from the closed list.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import BookingStatus
from app.modules.data_sources.domain_adapters import FileDomain, StoredProfile, domain_adapter
from app.modules.data_sources.errors import (
    InvalidRememberedAnswerError,
    RememberedAnswerNotFoundError,
)
from app.modules.data_sources.source_learning import (
    Learning,
    Memory,
    Trust,
    parse_learning,
    stored_learning,
)
from app.modules.data_sources.understanding_labor import DEPARTMENT_CHOICES
from app.modules.document_understanding.redaction import PersonalDataGuard
from app.modules.ingestion.models import DataSource, FileScope
from app.modules.invoices.cost_categories import CostCategory

logger = logging.getLogger(__name__)

# The same closed lists the import's own questions offer.
STATUS_CHOICES: tuple[str, ...] = (
    BookingStatus.CONFIRMED.value,
    BookingStatus.CANCELLED.value,
    BookingStatus.NO_SHOW.value,
    BookingStatus.CHECKED_IN.value,
    BookingStatus.CHECKED_OUT.value,
)
_FIELD_OF = {
    "status_mapping": "status",
    "channel_mapping": "channel",
    "role_mapping": "role",
    "category_mapping": "cost_category",
}
_CORRECTIONS_KEPT = 20
_WORD = "w-"
_FILE = "f-"


def _choices_of(document: str) -> tuple[str, ...]:
    """What a word may be corrected to. Empty: it can only be forgotten (nobody is asked about a
    channel word: it is an operator's, and it may rename a channel as well as classify it)."""
    if document == "status_mapping":
        return STATUS_CHOICES
    if document == "role_mapping":
        return tuple(category.value for category in DEPARTMENT_CHOICES)
    if document == "category_mapping":
        return tuple(category.value for category in CostCategory)
    return ()


def _closed(document: str, value: str) -> str | None:
    """A meaning, as the audit line may keep it: only one of the closed list. A channel word's
    meaning can be a name someone typed, and that is a value of a file."""
    return value if value in _choices_of(document) else None


@dataclass(frozen=True, slots=True)
class RememberedWord:
    id: str
    document: str
    field: str
    label: str
    value: str
    choices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RememberedFile:
    """One kind of file a person taught: what recognises it, and what it remembers beyond the
    columns."""

    id: str
    columns: tuple[str, ...]
    answers: tuple[tuple[str, str], ...]
    file_scope: FileScope | None
    column_decisions: int


@dataclass(frozen=True, slots=True)
class RememberedAnswers:
    data_source_id: UUID
    words: tuple[RememberedWord, ...]
    files: tuple[RememberedFile, ...]


def _word_id(document: str, label: str) -> str:
    """An opaque handle: the word itself travels in no address and in no log."""
    return _WORD + hashlib.sha256(f"{document}\0{label}".encode()).hexdigest()[:16]


def _value_of(document: str, value: Any) -> str | None:
    if document == "channel_mapping":
        if not isinstance(value, dict):
            return None
        meaning = value.get("channel_type") or value.get("name")
        return str(meaning) if meaning else None
    return str(value) if value else None


def _taught(memory: Memory) -> bool:
    """A family worth showing: a person decided something in it. One only the engine read has no
    authority over anything, unless a person said what its files hold."""
    return memory.trust == Trust.PERSON or memory.file_scope is not None


def read_answers(
    adapter: FileDomain, profile: StoredProfile | None, source_id: UUID
) -> RememberedAnswers:
    if profile is None:
        return RememberedAnswers(source_id, (), ())
    guard = PersonalDataGuard()
    words: list[RememberedWord] = []
    for document in adapter.value_documents:
        for label, raw in sorted(profile.documents.get(document, {}).items()):
            value = _value_of(document, raw)
            if value is None:
                continue
            words.append(
                RememberedWord(
                    id=_word_id(document, label),
                    document=document,
                    field=_FIELD_OF[document],
                    label=guard.clean(label),
                    value=value,
                    choices=_choices_of(document),
                )
            )
    learning = parse_learning((profile.documents.get("format_options") or {}).get("learning"))
    families = () if learning is None else tuple(learning.of_domain(adapter.domain.value).families)
    files = tuple(
        RememberedFile(
            id=_FILE + memory.id,
            columns=tuple(guard.clean(key) for key in memory.header_keys()),
            answers=tuple(sorted(memory.answers.items())),
            file_scope=memory.file_scope,
            column_decisions=len(memory.person),
        )
        for memory in families
        if _taught(memory)
    )
    return RememberedAnswers(source_id, tuple(words), files)


class RememberedAnswersService:
    """The person's correction of one source's memory. The caller holds the lock imports take and
    owns the transaction: this flushes, and never commits."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def _adapter(self, source: DataSource) -> FileDomain:
        adapter = domain_adapter(source.domain, self._session, self._tenant)
        if adapter is None:  # (a kind of data with no files to read has nothing remembered)
            raise RememberedAnswerNotFoundError()
        return adapter

    def read(self, source: DataSource) -> RememberedAnswers:
        adapter = domain_adapter(source.domain, self._session, self._tenant)
        if adapter is None:
            return RememberedAnswers(source.id, (), ())
        return read_answers(adapter, adapter.get_profile(source.id), source.id)

    def correct(
        self,
        source: DataSource,
        answer_id: str,
        value: str,
        *,
        by: UUID | None,
        now: datetime | None = None,
    ) -> RememberedAnswers:
        """Give a remembered word another meaning, within the list its question offers."""
        adapter = self._adapter(source)
        profile, document, label, before = self._word(adapter, source, answer_id)
        if value not in _choices_of(document):
            raise InvalidRememberedAnswerError()
        if before != value:
            changed = {**profile.documents[document], label: value}
            self._save(
                adapter,
                source,
                profile,
                {document: changed},
                now,
                by,
                {
                    "action": "CORRECTED",
                    "document": document,
                    "answer": answer_id,
                    "before": _closed(document, before),
                    "after": value,
                },
            )
        return read_answers(adapter, adapter.get_profile(source.id), source.id)

    def forget(
        self, source: DataSource, answer_id: str, *, by: UUID | None, now: datetime | None = None
    ) -> RememberedAnswers:
        """Forget one word, or one kind of file: nothing else changes."""
        adapter = self._adapter(source)
        if answer_id.startswith(_FILE):
            self._forget_file(adapter, source, answer_id, by, now)
        else:
            profile, document, label, before = self._word(adapter, source, answer_id)
            kept = {k: v for k, v in profile.documents[document].items() if k != label}
            self._save(
                adapter,
                source,
                profile,
                {document: kept},
                now,
                by,
                {
                    "action": "FORGOTTEN",
                    "document": document,
                    "answer": answer_id,
                    "before": _closed(document, before),
                    "after": None,
                },
            )
        return read_answers(adapter, adapter.get_profile(source.id), source.id)

    def _word(
        self, adapter: FileDomain, source: DataSource, answer_id: str
    ) -> tuple[StoredProfile, str, str, str]:
        profile = adapter.get_profile(source.id)
        if profile is None or not answer_id.startswith(_WORD):
            raise RememberedAnswerNotFoundError()
        for document in adapter.value_documents:
            for label, raw in profile.documents.get(document, {}).items():
                value = _value_of(document, raw)
                if value is not None and _word_id(document, label) == answer_id:
                    return profile, document, label, value
        raise RememberedAnswerNotFoundError()

    def _forget_file(
        self,
        adapter: FileDomain,
        source: DataSource,
        answer_id: str,
        by: UUID | None,
        now: datetime | None,
    ) -> None:
        profile = adapter.get_profile(source.id)
        learning = (
            None
            if profile is None
            else parse_learning((profile.documents.get("format_options") or {}).get("learning"))
        )
        family_id = answer_id.removeprefix(_FILE)
        target = None if learning is None else learning.family(family_id)
        if profile is None or learning is None or target is None or not _taught(target):
            raise RememberedAnswerNotFoundError()
        # (the saved matching is that family's when `current` names it: it is then nobody's, and
        # never applied to a file again by the family's authority)
        remaining = learning.model_copy(
            update={
                "families": [m for m in learning.families if m.id != family_id],
                "current": "" if learning.current == family_id else learning.current,
            }
        )
        self._save(
            adapter,
            source,
            profile,
            {},
            now,
            by,
            {
                "action": "FORGOTTEN",
                "document": "family",
                "answer": answer_id,
                "before": None,
                "after": None,
                "revision": target.revision,
            },
            learning=remaining,
        )

    def _save(
        self,
        adapter: FileDomain,
        source: DataSource,
        profile: StoredProfile,
        documents: dict[str, dict[str, Any]],
        now: datetime | None,
        by: UUID | None,
        entry: dict[str, Any],
        *,
        learning: Learning | None = None,
    ) -> None:
        options = dict(profile.documents.get("format_options") or {})
        store = learning or parse_learning(options.get("learning")) or Learning()
        entry = {
            **entry,
            "at": (datetime.now(UTC) if now is None else now).isoformat(),
            "by": None if by is None else str(by),
        }
        trail = [*store.corrections, entry][-_CORRECTIONS_KEPT:]
        options["learning"] = stored_learning(store.model_copy(update={"corrections": trail}))
        adapter.update_profile_documents(source.id, {**documents, "format_options": options})
        logger.info(
            "source memory corrected workspace_id=%s property_id=%s data_source_id=%s action=%s "
            "document=%s",
            self._tenant.workspace_id,
            source.property_id,
            source.id,
            entry["action"],
            entry["document"],
        )


__all__ = [
    "RememberedAnswers",
    "RememberedAnswersService",
    "RememberedFile",
    "RememberedWord",
    "STATUS_CHOICES",
    "read_answers",
]

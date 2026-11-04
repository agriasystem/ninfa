"""What an import was told about the records its file does not hold."""

from dataclasses import dataclass

from app.modules.ingestion.models import FileScope


@dataclass(frozen=True, slots=True)
class ScopePlan:
    """Decided by whoever read the file, before the import, and checked again under the source's
    lock: between the reading and the commit another file may have arrived.

    `expected_removals` is what that reading found would stop counting, the figure a person was
    shown. It never decides what is taken away, which is always computed again from what the source
    holds; it only says whether that is still what the person agreed to. None: no reading stands
    behind this import, and there is nothing to compare."""

    file_scope: FileScope | None = None
    remembered_file_scope: FileScope | None = None
    expected_removals: int | None = None

    def is_stale(self, removals: int) -> bool:
        return self.expected_removals is not None and removals != self.expected_removals


NO_SCOPE = ScopePlan()

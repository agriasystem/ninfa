"""The entries of the Product Knowledge Registry, one module per area, concatenated here."""

from app.modules.ai.mia.knowledge.entries import (
    dati,
    decision_intelligence,
    glossary,
    metrics,
    navigation,
    smart_import,
    states,
    struttura,
    workflows,
)
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

ALL_ENTRIES: tuple[KnowledgeEntry, ...] = (
    *navigation.ENTRIES,
    *dati.ENTRIES,
    *struttura.ENTRIES,
    *smart_import.ENTRIES,
    *decision_intelligence.ENTRIES,
    *metrics.ENTRIES,
    *states.ENTRIES,
    *workflows.ENTRIES,
    *glossary.ENTRIES,
)

__all__ = ["ALL_ENTRIES"]

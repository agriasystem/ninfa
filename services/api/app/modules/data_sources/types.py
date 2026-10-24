"""What a property's data sources are, in the words the Struttura page uses - never more than is
true.

NINFA has exactly ONE kind of data source today: a FILE (`DataSourceType.FILE_UPLOAD`) of one of
three domains (bookings, costs, labor). There is no automatic integration with a PMS, a Channel
Manager, an OTA, an accounting or an HR system, so nothing here can ever say that one is connected:
`CONNECTED` exists in the contract for the day an integration is real, and no code path of this
module produces it.

The five CARDS of the page (PMS, Channel Manager, OTA, Contabilità, Personale) are a presentation of
those three domains - a card is NOT a connection of its own:

- PMS            owns the bookings file (BOOKINGS);
- Channel Manager and OTA are never a connection of their own: the channel information arrives
  INSIDE the bookings file, so once bookings have been imported they read as DERIVED ("already
  received through another source") and the hotelier is never asked to link Booking.com or
  Expedia again;
- Contabilità    owns the costs files (COSTS, FatturaPA XML);
- Personale      owns the labor file (LABOR, CSV).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.ingestion.models import DataSourceDomain


class SourceCard(StrEnum):
    PMS = "PMS"
    CHANNEL_MANAGER = "CHANNEL_MANAGER"
    OTA = "OTA"
    ACCOUNTING = "ACCOUNTING"
    STAFF = "STAFF"


class SourceState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    # A file source exists (data arrive when someone uploads a file).
    CONFIGURED_FILE = "CONFIGURED_FILE"
    # A real automatic integration. NO code path produces it today.
    CONNECTED = "CONNECTED"
    # Received through another configured source (e.g. the OTA channels come with the bookings).
    DERIVED = "DERIVED"


class SourceMethod(StrEnum):
    CSV = "CSV"
    XML = "XML"


class DerivedFrom(StrEnum):
    BOOKINGS_FILE = "BOOKINGS_FILE"


@dataclass(frozen=True, slots=True)
class SourceCardState:
    card: SourceCard
    state: SourceState
    # The domain of the file source this card manages; `None` for the derived-only cards.
    domain: DataSourceDomain | None = None
    # `None` unless exactly one active source of the domain exists.
    data_source_id: UUID | None = None
    method: SourceMethod | None = None
    # When the latest SUCCEEDED import of this exact source finished. `None` = never imported.
    last_update_at: datetime | None = None
    # More than one active source of the domain (created outside this API): NINFA does not pick one.
    several_sources: bool = False
    derived_from: DerivedFrom | None = None
    # The automatic integration's own name. ALWAYS `None` today: no integration exists to name.
    provider: str | None = None
    # Real channel names read from the imported bookings (OTA card only).
    channels: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SourceCapability:
    """How a domain can REALLY be provided today."""

    domain: DataSourceDomain
    methods: tuple[SourceMethod, ...]


@dataclass(frozen=True, slots=True)
class SourcesOverview:
    property_id: UUID
    cards: tuple[SourceCardState, ...]
    capabilities: tuple[SourceCapability, ...]
    # Real automatic integrations NINFA can activate. Empty today, by design.
    automatic_integrations: tuple[str, ...] = ()


# The file method of each domain: the ONLY ways NINFA can receive data today.
DOMAIN_METHOD: dict[DataSourceDomain, SourceMethod] = {
    DataSourceDomain.BOOKINGS: SourceMethod.CSV,
    DataSourceDomain.COSTS: SourceMethod.XML,
    DataSourceDomain.LABOR: SourceMethod.CSV,
}

# What a source created through the API is called (a display name, never a vendor).
DOMAIN_SOURCE_NAME: dict[DataSourceDomain, str] = {
    DataSourceDomain.BOOKINGS: "Prenotazioni (file)",
    DataSourceDomain.COSTS: "Fatture (file)",
    DataSourceDomain.LABOR: "Personale (file)",
}

__all__ = [
    "DOMAIN_METHOD",
    "DOMAIN_SOURCE_NAME",
    "DerivedFrom",
    "SourceCapability",
    "SourceCard",
    "SourceCardState",
    "SourceMethod",
    "SourceState",
    "SourcesOverview",
]

import { describe, expect, it } from "vitest";

import {
  bookingsViaFile,
  channelManagerConnected,
  costsViaXml,
  laborViaCsv,
  nothingConfigured,
  sources,
} from "@/test/sources-support";

import { buildCardView, buildCardViews, formatSourceUpdate, nothingConfigured as isEmpty } from "./view-model";

const CONTEXT = { now: new Date("2026-10-23T10:00:00Z"), timeZone: "Europe/Rome" };

function view(response: ReturnType<typeof sources>, key: string) {
  const found = buildCardViews(response, CONTEXT).find((item) => item.key === key);
  if (!found) throw new Error(`no card ${key}`);
  return found;
}

describe("formatSourceUpdate", () => {
  it("says 'Oggi alle HH:MM' for today, in the PROPERTY's timezone", () => {
    expect(formatSourceUpdate("2026-10-23T07:31:00Z", CONTEXT)).toBe("Oggi alle 09:31");
  });

  it("says 'Ieri alle HH:MM' for the property-local yesterday", () => {
    expect(formatSourceUpdate("2026-10-22T16:04:00Z", CONTEXT)).toBe("Ieri alle 18:04");
  });

  it("reads an older update as the plain date with the year", () => {
    expect(formatSourceUpdate("2026-10-18T10:00:00Z", CONTEXT)).toBe("18 ottobre 2026");
  });

  it("decides today / yesterday with the property's timezone, not the browser's", () => {
    // 23:30 UTC on the 22nd is already 01:30 on the 23rd in Rome
    expect(formatSourceUpdate("2026-10-22T23:30:00Z", CONTEXT)).toBe("Oggi alle 01:30");
    expect(formatSourceUpdate("2026-10-22T23:30:00Z", { ...CONTEXT, timeZone: "America/New_York" })).toBe(
      "Ieri alle 19:30",
    );
  });

  it("never invents a date: no timestamp (or an unreadable one) is 'Mai importato'", () => {
    expect(formatSourceUpdate(null, CONTEXT)).toBe("Mai importato");
    expect(formatSourceUpdate("not a date", CONTEXT)).toBe("Mai importato");
  });
});

describe("a card that is not configured", () => {
  it("says so neutrally and offers to connect it", () => {
    const pms = view(nothingConfigured(), "PMS");

    expect(pms.line).toBe("Nessuna fonte collegata");
    expect(pms.pill).toEqual({ tone: "idle", text: "Non configurato" });
    expect(pms.meta).toBeNull();
    expect(pms.primary).toEqual({
      action: "connect",
      label: "Collega fonte",
      ariaLabel: "Collega fonte PMS",
    });
    expect(pms.secondary).toBeNull();
    expect(pms.menu.map((item) => item.label)).toEqual(["Collega fonte"]);
  });

  it("the OTA card says there is no channel data and offers 'Configura fonte', never 'Collega fonte'", () => {
    const ota = view(nothingConfigured(), "OTA");

    expect(ota.line).toBe("Nessun dato canale disponibile");
    expect(ota.primary?.label).toBe("Configura fonte");
    expect(ota.primary?.ariaLabel).toBe("Configura fonte OTA");
    expect(ota.menu.map((item) => item.label)).toEqual(["Configura fonte"]);
  });

  it("every card of an empty property reads the same neutral state", () => {
    for (const item of buildCardViews(nothingConfigured(), CONTEXT)) {
      expect(item.state).toBe("NOT_CONFIGURED");
      expect(item.pill.text).toBe("Non configurato");
    }
    expect(isEmpty(nothingConfigured())).toBe(true);
    expect(isEmpty(laborViaCsv())).toBe(false);
  });
});

describe("a card configured through a file", () => {
  it("shows how the data arrive, the real last update and the upload / manage actions", () => {
    const staff = view(laborViaCsv("2026-10-23T07:31:00Z"), "STAFF");

    expect(staff.line).toBe("Import CSV");
    expect(staff.pill).toEqual({ tone: "configured", text: "Configurato" });
    expect(staff.meta).toEqual({ label: "Ultimo aggiornamento", value: "Oggi alle 09:31" });
    expect(staff.primary?.label).toBe("Carica nuovo file");
    expect(staff.secondary?.label).toBe("Gestisci");
    expect(staff.menu.map((item) => item.label)).toEqual(["Gestisci", "Carica nuovo file", "Rimuovi fonte"]);
  });

  it("costs read 'Import fatture XML'", () => {
    expect(view(costsViaXml(), "ACCOUNTING").line).toBe("Import fatture XML");
  });

  it("a source that never completed an import is NOT configured: no 'Configurato', no 'Mai importato'", () => {
    const staff = view(laborViaCsv(null), "STAFF");

    expect(staff.state).toBe("NOT_CONFIGURED");
    expect(staff.line).toBe("Nessuna fonte collegata");
    expect(staff.pill).toEqual({ tone: "idle", text: "Non configurato" });
    expect(staff.meta).toBeNull();
    expect(staff.primary?.label).toBe("Collega fonte");
    expect(staff.secondary).toBeNull();
    expect(staff.menu.map((item) => item.label)).toEqual(["Collega fonte"]);
    expect(JSON.stringify(staff)).not.toMatch(/Configurato|Mai importato|Import CSV/u);
  });

  it("'nothing configured' counts such a card as not configured", () => {
    expect(isEmpty(laborViaCsv(null))).toBe(true);
    expect(isEmpty(laborViaCsv("2026-10-18T10:00:00Z"))).toBe(false);
  });

  it("several sources of a kind: nothing is claimed and no action is offered (the menu is not drawn)", () => {
    const staff = view(
      sources({ STAFF: { state: "CONFIGURED_FILE", several_sources: true, method: "CSV" } }),
      "STAFF",
    );

    expect(staff.line).toBe("Più fonti configurate");
    expect(staff.meta).toBeNull();
    expect(staff.primary).toBeNull();
    expect(staff.secondary).toBeNull();
    expect(staff.menu).toEqual([]);
  });
});

describe("a card received through another source", () => {
  it("the OTA card shows the REAL channels and 'Visualizza canali', not 'Collega fonte'", () => {
    const ota = view(bookingsViaFile(), "OTA");

    expect(ota.line).toBe("Booking.com · Expedia");
    expect(ota.pill).toEqual({ tone: "derived", text: "Già ricevuto" });
    expect(ota.meta).toEqual({ label: "Ricevuti tramite", value: "Prenotazioni importate" });
    expect(ota.primary?.action).toBe("view-channels");
    expect(ota.primary?.label).toBe("Visualizza canali");
    expect(ota.menu.map((item) => item.label)).toEqual(["Visualizza canali"]);
    expect(JSON.stringify(ota)).not.toContain("Collega");
  });

  it("without channel names it says the channels arrive with the bookings", () => {
    const ota = view(sources({ OTA: { state: "DERIVED", derived_from: "BOOKINGS_FILE", channels: [] } }), "OTA");

    expect(ota.line).toBe("Canali ricevuti con le prenotazioni");
  });

  it("the Channel Manager is not asked to be linked again once the bookings arrive", () => {
    const channelManager = view(bookingsViaFile(), "CHANNEL_MANAGER");

    expect(channelManager.line).toBe("Prenotazioni già ricevute");
    expect(channelManager.primary?.label).toBe("Visualizza");
    expect(channelManager.menu.map((item) => item.label)).toEqual(["Visualizza"]);
  });

  it("names the Channel Manager as the way the OTA data arrive when the backend says so", () => {
    expect(view(channelManagerConnected(), "OTA").meta?.value).toBe("Channel Manager");
  });
});

describe("a card that is connected automatically", () => {
  it("shows what the backend says - the integration's own name and a real update", () => {
    const channelManager = view(channelManagerConnected(), "CHANNEL_MANAGER");

    expect(channelManager.line).toBe("Fixture Channel Manager");
    expect(channelManager.pill).toEqual({ tone: "connected", text: "Connesso" });
    expect(channelManager.meta?.label).toBe("Ultimo aggiornamento");
    expect(channelManager.primary?.label).toBe("Gestisci");
  });

  it("without a name it says 'Connessione automatica', never a vendor", () => {
    const channelManager = sources().cards.find((item) => item.card === "CHANNEL_MANAGER");
    if (!channelManager) throw new Error("no card");
    const view_ = buildCardView({ ...channelManager, state: "CONNECTED", last_update_at: null }, CONTEXT);

    expect(view_.line).toBe("Connessione automatica");
    expect(view_.meta?.value).toBe("Mai importato");
  });
});

describe("the page invents nothing", () => {
  it("produces no vendor name and no age threshold: only what the backend sent", () => {
    for (const response of [nothingConfigured(), laborViaCsv(), costsViaXml(), bookingsViaFile()]) {
      const text = JSON.stringify(
        buildCardViews(response, CONTEXT).map((item) => [item.line, item.pill, item.meta, item.primary, item.secondary, item.menu]),
      );
      for (const vendor of ["Mews", "SiteMinder", "Cloudbeds", "TeamSystem"]) expect(text).not.toContain(vendor);
      expect(text).not.toMatch(/non aggiornat|potrebbero non essere|giorni fa/iu);
    }
  });
});

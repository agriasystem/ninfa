import type { DataSourceCard, DataSourcesResponse, SourceCardKey } from "@ninfa/contracts";

import {
  formatPropertyLocalDateLongItalian,
  formatPropertyLocalTimeItalian,
  previousBusinessDate,
  propertyLocalDate,
} from "@/lib/date/property-date";

import { sourcesCopy } from "./copy";

/**
 * What a card of "Fonti dati" shows, derived from the backend's own state - and nothing else. The page
 * never decides whether a source is connected, received or stale: it words what the backend says. A
 * missing timestamp reads "Mai importato" (never a guess) and no age threshold exists here: whether a
 * source is "old" is not a frontend judgement.
 *
 * A file source is "Configurato" only once it has delivered: a source whose last update the backend does
 * not know (it never completed a valid import) is shown as "Non configurato", exactly like no source at
 * all. The backend already answers this way; the page does not rely on that to stay truthful.
 */

export type SourceAction =
  | "connect"
  | "configure"
  | "upload"
  | "manage"
  | "remove"
  | "view-channels"
  | "view";

export type PillTone = "connected" | "configured" | "derived" | "idle";

export interface CardButton {
  action: SourceAction;
  label: string;
  /** The accessible name when the visible label alone would be ambiguous among five cards. */
  ariaLabel: string;
}

export interface SourceCardView {
  key: SourceCardKey;
  name: string;
  state: DataSourceCard["state"];
  /** The line under the name: how the data arrive, or that nothing does. */
  line: string;
  pill: { tone: PillTone; text: string };
  /** "Ultimo aggiornamento" / "Ricevuti tramite" with its value. */
  meta: { label: string; value: string } | null;
  primary: CardButton | null;
  secondary: CardButton | null;
  /** The "..." menu. Empty = the card has no menu: an action that cannot be used is never shown. */
  menu: CardButton[];
  /** The backend card the view was built from (the dialogs need its source id and domain). */
  card: DataSourceCard;
}

export interface ViewContext {
  now: Date;
  timeZone: string;
}

/** "Oggi alle 09:31" / "Ieri alle 18:04" / "18 ottobre 2026", in the PROPERTY's timezone. */
export function formatSourceUpdate(lastUpdateAt: string | null, { now, timeZone }: ViewContext): string {
  const copy = sourcesCopy.update;
  if (lastUpdateAt === null) return copy.never;
  const instant = new Date(lastUpdateAt);
  if (Number.isNaN(instant.getTime())) return copy.never;
  const today = propertyLocalDate(now, timeZone);
  const day = propertyLocalDate(instant, timeZone);
  const time = formatPropertyLocalTimeItalian(instant, timeZone);
  if (day === today) return copy.today(time);
  if (day === previousBusinessDate(today)) return copy.yesterday(time);
  return formatPropertyLocalDateLongItalian(instant, timeZone);
}

function button(action: SourceAction, label: string, ariaLabel: string): CardButton {
  return { action, label, ariaLabel };
}

/** A file source with no completed import behind it: nothing has been received, so nothing is configured. */
function neverDelivered(card: DataSourceCard): boolean {
  return card.state === "CONFIGURED_FILE" && !card.several_sources && card.last_update_at === null;
}

/** The state the page shows for a card (see the file header). */
function shownState(card: DataSourceCard): DataSourceCard["state"] {
  return neverDelivered(card) ? "NOT_CONFIGURED" : card.state;
}

export function buildCardView(card: DataSourceCard, context: ViewContext): SourceCardView {
  const text = sourcesCopy;
  const state = shownState(card);
  const name = text.cardLabels[card.card];
  const labels = text.actions;
  const isOta = card.card === "OTA";
  const connectLabel = isOta ? labels.configure : labels.connect;
  const connectAria = isOta ? labels.configureLabel(name) : labels.connectLabel(name);

  const base = { key: card.card, name, state, card };

  switch (state) {
    case "NOT_CONFIGURED": {
      const connect = button("connect", connectLabel, connectAria);
      return {
        ...base,
        line: isOta ? text.lines.noChannelData : text.lines.none,
        pill: { tone: "idle", text: text.state.notConfigured },
        meta: null,
        primary: connect,
        secondary: null,
        menu: [button(isOta ? "configure" : "connect", connectLabel, connectAria)],
      };
    }
    case "CONFIGURED_FILE": {
      const method = card.method !== null ? text.methodLabels[card.method] : text.lines.none;
      if (card.several_sources) {
        // Created outside this page: NINFA does not pick one, so there is nothing to manage here.
        return {
          ...base,
          line: text.lines.several,
          pill: { tone: "configured", text: text.state.configured },
          meta: null,
          primary: null,
          secondary: null,
          menu: [],
        };
      }
      // The accessible name starts with the visible label (label-in-name) and adds the card it acts on.
      const upload = button("upload", labels.uploadNew, `${labels.uploadNew} ${name}`);
      const manage = button("manage", labels.manage, labels.manageLabel(name));
      return {
        ...base,
        line: method,
        pill: { tone: "configured", text: text.state.configured },
        meta: { label: text.update.label, value: formatSourceUpdate(card.last_update_at, context) },
        primary: upload,
        secondary: manage,
        menu: [manage, upload, button("remove", labels.remove, labels.remove)],
      };
    }
    case "CONNECTED": {
      const manage = button("manage", labels.manage, labels.manageLabel(name));
      return {
        ...base,
        line: card.provider ?? text.lines.automatic,
        pill: { tone: "connected", text: text.state.connected },
        meta: { label: text.update.label, value: formatSourceUpdate(card.last_update_at, context) },
        primary: manage,
        secondary: null,
        menu: [manage],
      };
    }
    case "DERIVED": {
      const view = isOta
        ? button("view-channels", labels.viewChannels, labels.viewChannels)
        : button("view", labels.view, labels.viewLabel(name));
      const via = card.derived_from ?? "BOOKINGS_FILE";
      return {
        ...base,
        line: isOta
          ? card.channels.length > 0
            ? card.channels.join(" · ")
            : text.lines.channelsReceived
          : text.lines.bookingsReceived,
        pill: { tone: "derived", text: text.state.derived },
        meta: { label: text.receivedVia.label, value: text.receivedVia[via] },
        primary: view,
        secondary: null,
        menu: [view],
      };
    }
  }
}

/** The cards in the page's order, exactly as the backend listed them. */
export function buildCardViews(sources: DataSourcesResponse, context: ViewContext): SourceCardView[] {
  return sources.cards.map((card) => buildCardView(card, context));
}

/** `true` when no card is configured, connected or received: the section then shows its introduction. */
export function nothingConfigured(sources: DataSourcesResponse): boolean {
  return sources.cards.every((card) => shownState(card) === "NOT_CONFIGURED");
}

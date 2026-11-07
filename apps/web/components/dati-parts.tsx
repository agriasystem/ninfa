"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import type { NightStatus } from "@ninfa/contracts";

import { datiCopy, nightStatusText } from "@/lib/data/copy";
import { strutturaInventoryRoute } from "@/lib/routes";

/** The one white rounded card of the Dati workspace. `title` is the card's `<h2>`; a card without a
 * visible title passes `label` instead (still a named region, so a screen reader lists it). */
export function DatiCard({
  id,
  title,
  label,
  className,
  actions,
  children,
}: {
  id: string;
  title?: ReactNode;
  label?: string;
  className?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const titleId = `${id}-title`;
  return (
    <section
      className={`dati-card${className ? ` ${className}` : ""}`}
      aria-labelledby={title !== undefined ? titleId : undefined}
      aria-label={title === undefined ? label : undefined}
    >
      {title !== undefined ? (
        <header className="dati-card__header">
          <h2 id={titleId} className="dati-card__title">
            {title}
          </h2>
          {actions}
        </header>
      ) : null}
      {children}
    </section>
  );
}

/** A designed empty state INSIDE a card (never a blank area): a title, one plain sentence and, when the
 * person can do something about it, the one next step. */
export function DatiEmpty({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="dati-empty" role="status">
      <p className="dati-empty__title">{title}</p>
      {body ? <p className="dati-empty__body">{body}</p> : null}
      {action}
    </div>
  );
}

/** "Configura inventario": straight to the room inventory block of Struttura - the one place the number
 * of rooms is configured. Dati never offers a second setting of its own. */
export function ConfigureInventoryLink({ propertyId }: { propertyId: string }) {
  return (
    <Link className="dati-cta" href={strutturaInventoryRoute(propertyId)}>
      {datiCopy.occupancy.configureInventory}
    </Link>
  );
}

/** A change chip. Deliberately NEUTRAL: the backend has no notion of "good" or "bad" for a change,
 * so no green or red is ever painted on one - the sign and the stated comparison say everything. */
export function DeltaChip({ text, label }: { text: string; label?: string }) {
  return (
    <span className="dati-delta" aria-label={label ?? text}>
      {text}
    </span>
  );
}

/** A night's status: always its WORD (never colour alone), plus a small shape that differs by state. */
export function StatusMark({ status }: { status: NightStatus }) {
  return (
    <span className={`dati-status dati-status--${status.toLowerCase().replace("_", "-")}`}>
      <span className="dati-status__mark" aria-hidden="true" />
      {nightStatusText(status)}
    </span>
  );
}

import type { ComponentType, ReactNode, SVGProps } from "react";

import Link from "next/link";

import { MoreIcon } from "./icons";

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

/**
 * What the buttons of the Struttura page do. The profile, the room inventory and the parameters are NOT
 * wired yet (the structure has no write path for them), so those callbacks are optional and the buttons are
 * drawn, real and focusable, ready for the day they get one. "Fonti dati" is fully wired and needs none: it
 * opens its own dialogs (see `struttura-sources.tsx`). No callback here ever fabricates a workflow.
 */
export interface StrutturaActions {
  onEditStructure?: () => void;
  onEditInventory?: () => void;
  /** "Configura inventario": the empty state's way to set the room types up for the first time. */
  onConfigureInventory?: () => void;
  onEditParameters?: () => void;
  onRoomMenu?: (roomId: string) => void;
}

export interface StrutturaButtonProps {
  /** `soft`: the light-blue "Modifica ..."; `primary`: the filled blue call to action; `outline`: the
   * quiet "Collega fonte" inside a card. */
  variant: "soft" | "primary" | "outline";
  Icon?: IconComponent;
  onClick?: () => void;
  /** Overrides the accessible name when the visible text alone is ambiguous (two "Collega fonte"). */
  ariaLabel?: string;
  disabled?: boolean;
  /** A button that opens or closes something: whether it is open now. */
  expanded?: boolean;
  children: ReactNode;
}

export function StrutturaButton({
  variant,
  Icon,
  onClick,
  ariaLabel,
  disabled,
  expanded,
  children,
}: StrutturaButtonProps) {
  return (
    <button
      type="button"
      className={`struttura-button struttura-button--${variant}`}
      aria-label={ariaLabel}
      aria-expanded={expanded}
      disabled={disabled}
      onClick={onClick}
    >
      {Icon ? <Icon className="struttura-button__icon" /> : null}
      {children}
    </button>
  );
}

/** A link that looks exactly like a `StrutturaButton`: "Visualizza canali" goes to a page, it opens nothing. */
export function StrutturaLinkButton({
  variant,
  href,
  ariaLabel,
  children,
}: {
  variant: StrutturaButtonProps["variant"];
  href: string;
  ariaLabel?: string;
  children: ReactNode;
}) {
  return (
    <Link
      className={`struttura-button struttura-button--${variant}`}
      href={href}
      aria-label={ariaLabel}
    >
      {children}
    </Link>
  );
}

/** The "..." trigger of a row or a card. It names what it acts on and opens nothing yet. */
export function StrutturaMoreButton({
  label,
  className,
  onClick,
}: {
  label: string;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      className={className ? `struttura-more ${className}` : "struttura-more"}
      aria-label={label}
      aria-haspopup="menu"
      onClick={onClick}
    >
      <MoreIcon className="struttura-more__icon" />
    </button>
  );
}

export interface StrutturaSectionProps {
  /** Unique on the page: it names the heading the card is labelled by. */
  id: string;
  Icon: IconComponent;
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
}

/** One numbered card of the page: icon tile, title and description on the left, an optional action on the
 * right, then the card's own content. A labelled region, so a screen reader can jump between the four. */
export function StrutturaSection({ id, Icon, title, description, action, children }: StrutturaSectionProps) {
  const titleId = `${id}-title`;
  return (
    <section className="struttura-card" aria-labelledby={titleId}>
      <header className="struttura-card__header">
        <span className="struttura-card__icon" aria-hidden="true">
          <Icon />
        </span>
        <div className="struttura-card__heading">
          <h2 id={titleId} className="struttura-card__title">
            {title}
          </h2>
          <p className="struttura-card__description">{description}</p>
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

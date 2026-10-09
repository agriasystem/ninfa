"use client";

import Link from "next/link";
import type { ComponentType, RefObject, SVGProps } from "react";

import { copy } from "@/lib/copy";
import { decisioniRoute, oggiRoute } from "@/lib/routes";

import { BarsIcon, DatabaseIcon, DecisionsIcon, HomeIcon, SettingsIcon } from "./icons";
import { NinfaLogo } from "./ninfa-logo";
import { ProfileMenu } from "./profile-menu";

/** Which section of the sidebar is the current one. The Decision Detail page belongs to
 * "decisioni" (its back link is "← Decisioni"), so it highlights the same item. */
export type ShellSection = "oggi" | "decisioni";

export interface AppSidebarProps {
  /** `""` when the account has no property: the links then carry no `?property=`. */
  selectedPropertyId: string;
  activeSection: ShellSection;
  /** Hides the small logo (the Home's hero logo is showing) - its box is always kept. */
  logoHidden: boolean;
  logoSlotRef: RefObject<HTMLDivElement | null>;
  displayName: string | null;
  email: string | null;
  onLogout: () => void;
}

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

interface LiveItem {
  kind: "link";
  section: ShellSection;
  label: string;
  Icon: IconComponent;
  href: (propertyId: string) => string;
}

interface SoonItem {
  kind: "soon";
  key: string;
  label: string;
  Icon: IconComponent;
}

const NAV_ITEMS: readonly (LiveItem | SoonItem)[] = [
  {
    kind: "link",
    section: "oggi",
    label: copy.nav.today,
    Icon: HomeIcon,
    href: (propertyId) => oggiRoute(propertyId || undefined),
  },
  {
    kind: "link",
    section: "decisioni",
    label: copy.nav.decisions,
    Icon: DecisionsIcon,
    href: (propertyId) => decisioniRoute(propertyId || undefined),
  },
  { kind: "soon", key: "dati", label: copy.nav.data, Icon: BarsIcon },
  { kind: "soon", key: "struttura", label: copy.nav.structure, Icon: DatabaseIcon },
];

/**
 * A section that does not exist yet (Dati, Struttura, Impostazioni): drawn in the approved layout,
 * but NEVER a link - no `href`, not focusable, `aria-disabled="true"`, with a discreet "In arrivo".
 * It does not navigate and no page behind it exists; a placeholder route would misrepresent the
 * product (see docs/architecture/oggi-ui-v1.md, "Authenticated shell").
 */
function ComingSoonItem({ item }: { item: SoonItem }) {
  return (
    <span className="nav-item nav-item--soon" role="link" aria-disabled="true">
      <item.Icon className="nav-item__icon" />
      <span className="nav-item__text">
        <span className="nav-item__label">{item.label}</span>
        <span className="nav-item__soon">{copy.nav.comingSoon}</span>
      </span>
    </span>
  );
}

/** The approved sidebar (Home UI V1): logo slot, the four sections, then profile | settings. */
export function AppSidebar({
  selectedPropertyId,
  activeSection,
  logoHidden,
  logoSlotRef,
  displayName,
  email,
  onLogout,
}: AppSidebarProps) {
  return (
    <aside className="app-sidebar">
      <Link
        className="app-sidebar__logo"
        href={oggiRoute(selectedPropertyId || undefined)}
        aria-label={copy.nav.logoHome}
      >
        <div
          ref={logoSlotRef}
          className="app-sidebar__logo-slot"
          data-hidden={logoHidden ? "true" : "false"}
        >
          <NinfaLogo className="app-sidebar__logo-image" />
        </div>
      </Link>

      <nav className="app-sidebar__nav" aria-label={copy.nav.mainLabel}>
        <ul>
          {NAV_ITEMS.map((item) => (
            <li key={item.kind === "link" ? item.section : item.key}>
              {item.kind === "link" ? (
                <Link
                  className="nav-item"
                  href={item.href(selectedPropertyId)}
                  aria-current={item.section === activeSection ? "page" : undefined}
                >
                  <item.Icon className="nav-item__icon" />
                  <span className="nav-item__label">{item.label}</span>
                </Link>
              ) : (
                <ComingSoonItem item={item} />
              )}
            </li>
          ))}
        </ul>
      </nav>

      <div className="app-sidebar__footer" role="group" aria-label={copy.nav.secondaryLabel}>
        <ProfileMenu displayName={displayName} email={email} onLogout={onLogout} />
        <span className="app-sidebar__divider" aria-hidden="true" />
        <span
          className="nav-item nav-item--soon nav-item--icon-only"
          role="link"
          aria-disabled="true"
          aria-label={`${copy.nav.settings} (${copy.nav.comingSoon.toLowerCase()})`}
        >
          <SettingsIcon className="nav-item__icon" />
        </span>
      </div>
    </aside>
  );
}

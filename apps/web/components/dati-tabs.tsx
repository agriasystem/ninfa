"use client";

import { useRef, type KeyboardEvent } from "react";

import type { DataPeriod } from "@ninfa/contracts";

import { datiCopy } from "@/lib/data/copy";
import { DATI_TABS, type DatiTab } from "@/lib/data/tabs";

export function datiTabId(tab: DatiTab): string {
  return `dati-tab-${tab}`;
}

export function datiPanelId(tab: DatiTab): string {
  return `dati-panel-${tab}`;
}

export interface DatiTabsProps {
  active: DatiTab;
  onSelect: (tab: DatiTab) => void;
}

/**
 * The five internal sections of Dati, drawn as the reference's compact pill tabs - NOT a second
 * application navigation (the sidebar is the only one). Semantics are the WAI-ARIA tabs pattern with
 * MANUAL activation: Left / Right / Home / End move focus between the tabs (roving tabindex: only the
 * selected tab is in the tab order) and Enter / Space selects, so keyboard users never trigger a
 * navigation by merely browsing. Each tab controls the panel `datiPanelId(tab)`.
 */
export function DatiTabs({ active, onSelect }: DatiTabsProps) {
  const refs = useRef<Partial<Record<DatiTab, HTMLButtonElement | null>>>({});

  function focusTab(index: number) {
    const tab = DATI_TABS[(index + DATI_TABS.length) % DATI_TABS.length];
    if (tab !== undefined) refs.current[tab]?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        focusTab(index + 1);
        break;
      case "ArrowLeft":
        event.preventDefault();
        focusTab(index - 1);
        break;
      case "Home":
        event.preventDefault();
        focusTab(0);
        break;
      case "End":
        event.preventDefault();
        focusTab(DATI_TABS.length - 1);
        break;
    }
  }

  return (
    <div className="dati-tabs-scroller">
      <div role="tablist" aria-label={datiCopy.tabsLabel} className="dati-tabs">
        {DATI_TABS.map((tab, index) => {
          const selected = tab === active;
          return (
            <button
              key={tab}
              ref={(element) => {
                refs.current[tab] = element;
              }}
              type="button"
              role="tab"
              id={datiTabId(tab)}
              aria-selected={selected}
              aria-controls={datiPanelId(tab)}
              tabIndex={selected ? 0 : -1}
              className="dati-tab"
              onClick={() => onSelect(tab)}
              onKeyDown={(event) => handleKeyDown(event, index)}
            >
              {datiCopy.tabs[tab]}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export interface DatiPeriodControlProps {
  period: DataPeriod;
  onSelect: (period: DataPeriod) => void;
  /** `true` while a different period is being fetched: the choice is already made. */
  busy?: boolean;
}

const PERIODS: readonly { value: DataPeriod; label: string }[] = [
  { value: 7, label: datiCopy.period.days7 },
  { value: 30, label: datiCopy.period.days30 },
];

/** 7 / 30 days: compact period controls (the reference's large buttons, resized to NINFA). The
 * pressed state is exposed through `aria-pressed`, not colour alone. */
export function DatiPeriodControl({ period, onSelect, busy = false }: DatiPeriodControlProps) {
  return (
    <div role="group" aria-label={datiCopy.period.groupLabel} className="dati-period" aria-busy={busy}>
      {PERIODS.map((item) => (
        <button
          key={item.value}
          type="button"
          className="dati-period__option"
          aria-pressed={item.value === period}
          onClick={() => onSelect(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

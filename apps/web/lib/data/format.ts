import { formatDecimal, formatPercent } from "@/lib/decisions/format";

/**
 * DISPLAY-ONLY formatting for Dati, on top of `lib/decisions/format.ts`. Same contract: every value
 * is a figure the backend already calculated (a two-decimal string, or an integer count) and nothing
 * here is ever fed back into a comparison, a threshold or a rank. Parsing a string into a number
 * happens only at the last step, for `Intl` to round for a person to read.
 */

export const MISSING = "—";

// A typographic minus (U+2212): it reads as a sign, never as a hyphen, in a narrow chip.
const MINUS = "−";

function parsed(value: string | null): number | null {
  if (value === null) return null;
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : null;
}

/** Thousands are grouped everywhere in Dati ("1.160", "1.700 €"): Intl's default leaves a four-digit
 * number bare, and `formatCount` (shared with the rest of the app) groups it - one convention per page.
 *
 * "+12", "−5", "0" - an integer change. */
export function formatSignedCount(value: number | null): string {
  if (value === null) return MISSING;
  const grouped = Math.abs(value).toLocaleString("it-IT", { maximumFractionDigits: 0, useGrouping: true });
  if (value > 0) return `+${grouped}`;
  if (value < 0) return `${MINUS}${grouped}`;
  return "0";
}

/** "+100,0%", "−4,2%", "0,0%" - a percentage change already on the 0-100 scale. */
export function formatSignedPercent(value: string | null, fractionDigits = 1): string {
  const number = parsed(value);
  if (number === null) return MISSING;
  const body = formatPercent(String(Math.abs(number)), fractionDigits);
  if (number > 0) return `+${body}`;
  if (number < 0) return `${MINUS}${body}`;
  return body;
}

/** A money amount as whole currency units for a large figure ("38.250 €"). The cents are the
 * backend's; showing them on a headline number would only be noise. */
export function formatMoneyWhole(amount: string | null, currency: string): string {
  const number = parsed(amount);
  if (number === null) return MISSING;
  try {
    return number.toLocaleString("it-IT", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
      minimumFractionDigits: 0,
      useGrouping: true,
    });
  } catch {
    return `${formatDecimal(amount, 0)} ${currency}`;
  }
}

/** A money amount with cents ("116,67 €") - an ADR, a per-room cost. */
export function formatMoneyCents(amount: string | null, currency: string): string {
  const number = parsed(amount);
  if (number === null) return MISSING;
  try {
    return number.toLocaleString("it-IT", { style: "currency", currency, useGrouping: true });
  } catch {
    return `${formatDecimal(amount, 2)} ${currency}`;
  }
}

export { formatDecimal, formatPercent };

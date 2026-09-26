/**
 * DISPLAY-ONLY number formatting. Every function here takes a value the backend already decided
 * with (a Decimal-as-string, an already-times-100 percentage-point value - see each intelligence
 * module's own `precision.py` and its `percent_of()` helper - or a plain integer count) and
 * turns it into Italian-locale prose. Nothing here is ever fed back into a comparison, a
 * threshold or a rank: parsing a string into a number happens ONLY at the last possible step,
 * for `Intl.NumberFormat` to round for a human to read.
 */

const MISSING = "—";

function parsed(value: string | null): number | null {
  if (value === null) return null;
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : null;
}

export function formatDecimal(value: string | null, fractionDigits = 1): string {
  const number = parsed(value);
  if (number === null) return MISSING;
  return number.toLocaleString("it-IT", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

/** `value` is ALREADY on the 0-100 scale (every `*_percent_exact`/`*_pp_exact`/`*_share_exact`
 * fact is computed via the backend's own `percent_of()`, which multiplies by 100 itself) - this
 * NEVER multiplies by 100 again. */
export function formatPercent(value: string | null, fractionDigits = 1): string {
  const formatted = formatDecimal(value, fractionDigits);
  return formatted === MISSING ? MISSING : `${formatted}%`;
}

export function formatCount(value: number | null): string {
  if (value === null) return MISSING;
  return value.toLocaleString("it-IT", { maximumFractionDigits: 0, useGrouping: true });
}

export function formatHours(value: string | null, fractionDigits = 1): string {
  const formatted = formatDecimal(value, fractionDigits);
  return formatted === MISSING ? MISSING : `${formatted} h`;
}

/** `amount` + `currency` -> localised money, e.g. "€ 128,40". Never labelled "perdita"/"risparmio"
 * here - that framing decision belongs to the caller, using the contract's own `label`. */
export function formatMoney(amount: string, currency: string): string {
  const number = Number.parseFloat(amount);
  if (!Number.isFinite(number)) return MISSING;
  try {
    return number.toLocaleString("it-IT", { style: "currency", currency });
  } catch {
    return `${formatDecimal(amount, 2)} ${currency}`;
  }
}

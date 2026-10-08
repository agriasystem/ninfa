/**
 * "Ciao {Nome}," (Home UI V1). The session carries ONE free-text `display_name` (no given name /
 * family name split exists), so the first whitespace-separated token is used as the greeting name.
 * That is a heuristic and an honest one: "Rossi Mario" would greet "Rossi" - the pilot onboarding
 * doc asks for "Nome Cognome". A null/blank display name returns `null` (the greeting then reads
 * "Ciao,") and a name is NEVER derived from the e-mail address.
 */
export function firstNameOf(displayName: string | null | undefined): string | null {
  if (displayName === null || displayName === undefined) return null;
  const [first] = displayName.trim().split(/\s+/u);
  return first === undefined || first.length === 0 ? null : first;
}

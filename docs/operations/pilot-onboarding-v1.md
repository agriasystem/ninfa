# First customer onboarding runbook V1 (Gate 27B)

Exact steps, using only supported CLI commands (no SQL). Each step is tagged:
**[INFRA]** infrastructure/developer, **[OPERATOR]** AGRIA operator, **[CUSTOMER]** the hotel.
`ninfa-py` is defined in the [deployment document](pilot-deployment-v1.md) ("Operator shell
helpers"). Slugs are lowercase letters, digits and hyphens (for example `hotel-aurora`).

## Set the expectation first (cold start)

**Tell the hotel before anything else:** NINFA builds its comparison history **day by day**. For
roughly the **first five weeks** Oggi will mostly show a **limited-data-quality** state
(`DATA_QUALITY_LIMITED`), not full decision coverage. This is derived from the detectors' minimum
of five comparable same-weekday observed snapshots (≈ 35 days of uninterrupted daily analysis).
**Importing historical bookings does not by itself create that history**: observed snapshots exist
only for the days NINFA actually analysed, and there is no supported command that reconstructs them.
Every missed day delays the moment decisions become meaningful. Do **not** promise full coverage on
day 1. See [pilot expectations](pilot-expectations-v1.md).

## Before onboarding — [INFRA]

- [ ] The deployment is complete and the [smoke checklist](pilot-smoke-checklist-v1.md) passed.
- [ ] A **backup restore has been tested successfully** ([backup and restore](pilot-backup-restore-v1.md)).
- [ ] The **daily scheduler** is configured for 10:00 `Europe/Rome` and its DST behaviour verified.
- [ ] If Ask NINFA is to be on: all five conditions of the policy are met (otherwise it stays off).
- [ ] The hotel's export format is understood and can be normalized to the canonical CSV.

## Steps

1. **[OPERATOR] Workspace.**
   `ninfa-py -m app.cli.pilot create-workspace --name "<Hotel name>" --slug <workspace-slug>`
2. **[OPERATOR] Property.**
   `ninfa-py -m app.cli.pilot create-property --workspace-slug <workspace-slug> --name "<Hotel name>" --slug <property-slug> --timezone Europe/Rome --currency EUR`
3. **[OPERATOR] User.**
   `ninfa-py -m app.cli.pilot create-user --email <user@hotel> --display-name "<Name>"`
4. **[OPERATOR] Password.** `ninfa-py -m app.cli.auth set-password --email <user@hotel>`: the prompt
   asks twice and never echoes (14 to 128 characters). There is **no self-service password change or
   reset**: the operator sets it, hands it to the customer through a **different secure channel**,
   and re-runs the command to rotate it (which also revokes the user's sessions).
5. **[OPERATOR] Owner membership.**
   `ninfa-py -m app.cli.pilot grant-access --workspace-slug <workspace-slug> --email <user@hotel> --role OWNER`
6. **[OPERATOR] BOOKINGS data source.**
   `ninfa-py -m app.cli.pilot create-data-source --workspace-slug <workspace-slug> --property-slug <property-slug> --domain BOOKINGS --name "Bookings"`
   — **record the printed data source id in AGRIA's own records** (there is no list command).
7. **[OPERATOR] Room inventory.**
   `ninfa-py -m app.cli.pilot set-room-inventory --workspace-slug <workspace-slug> --property-slug <property-slug> --stay-date-start <today> --stay-date-end <far date> --rooms-available <N> [--rooms-out-of-order <M>]`
   Cover **well beyond** the rolling 30-date window and put the extension in AGRIA's calendar:
   nothing extends it automatically. Use several ranges if capacity changes by season.
8. **[OPERATOR] Initial canonical booking import**, following the file-intake procedure in
   [daily operations](pilot-daily-operations-v1.md). Include the bookings with stay dates in the
   coming 30 days; historical rows are accepted but, as above, do not create the observed history.
   Confirm `status=SUCCEEDED`.
9. **[OPERATOR] Enable automatic analysis** with the exact data source id:
   `ninfa-py -m app.cli.analysis_policy enable --workspace-slug <workspace-slug> --property-slug <property-slug> --booking-data-source-id <id>`
   then `ninfa-py -m app.cli.analysis_policy show …` must say `configuration=VALID`. Enabling never
   runs anything by itself.
10. **[OPERATOR] First run, or the next scheduled opportunity.** After the import (a same-day catch-up
    is supported), run the wrapper as in daily operations, or let the next 10:00 run do it. Then
    `ninfa-py -m worker analysis-status` must show `run_today=YES` for the property. If today's
    import was not done, the property is skipped until it is.
11. **[CUSTOMER] Login verification.** The hotel opens `https://<origin>`, logs in with the email and
    the password received separately, and reaches Oggi.
12. **[CUSTOMER] + [OPERATOR] Oggi verification.** Oggi opens and shows an **honest** state: after the
    first run the limited-data state, the line "Non analizzati: Costi, Personale." and the booking
    freshness. The operator confirms with the hotel what they see; the operator does not log in as
    the customer.
13. **[OPERATOR] Ask NINFA verification, only if enabled.** Open a decision and ask one question
    (a Decision must exist; during the cold start there may be none yet, so this may have to wait).

## Steps that still need a developer or infrastructure person

- The first deployment, DNS/TLS and the scheduler ([INFRA]).
- A hotel export that cannot be reshaped into the canonical CSV with a spreadsheet.
- Anything that needs the database directly: it is not part of the normal workflow.

## Not supported yet (tell the hotel)

Self-service signup or password change, an upload screen, native PMS connections, automatic costs
and labor analysis, alerts or notifications, and a command that rebuilds past observation history.

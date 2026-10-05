# Pilot expectations V1 (Gate 27B)

What AGRIA should tell a pilot hotel, and what NINFA can and cannot do in the first pilot. Written
for AGRIA staff; keep it consistent with what the product really does.

## What NINFA does every day

Once the hotel's booking file is imported, NINFA analyses the **next 30 stay dates** of the property
at **10:00 property-local time**, for **revenue** (booking pace and occupancy risk) and
**distribution** (channel concentration). The hotel opens **Oggi** to see the result, together with
what was analysed and how fresh the booking data was.

## Cold start: do not promise full coverage on day 1

- For roughly the **first five weeks** the hotel should expect **mostly "limited data quality"**
  (`DATA_QUALITY_LIMITED`) and few or no decisions. The reason: the detectors compare a stay night
  with at least five comparable observed snapshots of the same weekday and lead time, and those are
  built **one day at a time** (about 35 days of uninterrupted daily analysis). This is derived from
  the detectors' existing minimums, not a measured guarantee.
- **Importing historical bookings does not by itself create that history.** NINFA stores an
  observed snapshot only for the days it analysed, and no supported command reconstructs earlier
  days.
- **Every day the analysis does not run delays the moment decisions become meaningful**, and a
  day that was missed cannot be recovered. Daily imports before the cut-off matter.
- Oggi is designed to be honest in this phase: it says the analysis is limited, never "all clear"
  because data is missing.

## What the hotel must do

Provide the booking export **every day before 09:45** (local time) through the channel agreed with
AGRIA. NINFA does not pull data from the PMS: the file import is manual, done by an AGRIA operator.

## What is not analysed

**Costs and Personale (labor) are not analysed automatically** in this pilot. Oggi says so on every
day ("Non analizzati: Costi, Personale."): "nothing to do" only means nothing was found in the areas
that were analysed.

## Ask NINFA

Available **only once AGRIA has enabled it** (a provider-side spending limit, a real smoke test and
telemetry must be in place), and only on an existing decision. It explains a decision from NINFA's
own data; it is not a general assistant. If it is not enabled it simply answers that it is
unavailable.

## Not available in the first pilot

A direct connection to the PMS, self-service uploads, self-service password changes, alerts or
notifications, past-history rebuilding, and an application-level limit on Ask NINFA usage.

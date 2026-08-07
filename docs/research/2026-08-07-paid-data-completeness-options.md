# Paid data-completeness options

**Status:** potential future fallback, not an active dependency

**Reviewed:** 2026-08-07

**Current decision:** continue production with the current free SEC, Yahoo and local evidence layers.

## Why this document exists

The reliable Scout coverage after the free-data build is 65,834 of 123,968
metric cells (53.106%). Paid data may later supplement genuine disclosure and
history gaps, but vendor values must never silently replace filed evidence.

The active universe has 7,486 securities, of which 5,763 are currently
eligible. The eligible exchange split used during this review contained 5,713
NYSE/Nasdaq listings and 50 Amsterdam listings. Vendor marketing counts are
therefore not evidence of overlap with our universe.

## Candidate comparison

| Route | Confirmed reach | Lineage | Indicative cost at review | Best use |
|---|---|---|---|---|
| SEC + AFM/ESEF | US + Dutch filed reports | Excellent | Free | Primary evidence layer |
| SimFin Basic | Nearly 5,000 US stocks | Good; standardized and as-reported data with report traceability | $35/month billed annually, $420/year | Low-cost US supplement |
| SimFin Pro | Same candidate family with higher limits/history | Good | $71/month billed annually, $852/year | Only if a measured pilot proves Basic limits insufficient |
| EODHD Fundamentals | Global catalog; Amsterdam explicitly listed as AS/XAMS | Medium; validate against filings | EUR 59.99/month or EUR 599.90/year | Single-vendor US + Amsterdam fallback |
| FMP | Strong US catalog; Amsterdam fundamentals not yet proven for this use | Medium | Plan-dependent | Pilot only |
| eToro Public API | Prices and instruments | Not a fundamental filing source | Account/API dependent | Price and symbol verification only |

Prices and plan limits can change. Re-check official terms immediately before
purchase.

## SimFin assessment

SimFin is a credible and relatively inexpensive US-fundamentals candidate. Its
official material describes nearly 5,000 US stocks, more than 620,000 financial
statements, standardized and as-reported bulk data from Basic, internal QA and
links back to company reports.

It is not yet validated for this system. Without an API key we have not measured:

- exact overlap with the 5,713 eligible NYSE/Nasdaq listings;
- incremental coverage across the 33,341 cells needed to reach 80%;
- conflicts with current SEC facts and accessions;
- filing-date, unit, currency and restatement fidelity;
- explicit coverage of Amsterdam primary listings.

Basic is the first paid tier worth testing. Pro should only be selected after a
pilot demonstrates that Basic throughput or history prevents a useful backfill.

## Dutch equities

AFM/ESEF remains the preferred source for Dutch primaries because it provides
filed iXBRL/XBRL reports with strong period and filing lineage. It requires an
IFRS-to-Scout concept map, but preserves the evidence standard.

EODHD explicitly catalogs Euronext Amsterdam under exchange code `AS` and MIC
`XAMS`, and reported 531 active Amsterdam tickers during this review. It is the
strongest current single-vendor candidate for wider geographic coverage, but
its normalized fundamentals must be treated as fallback observations and
checked against AFM/ESEF filings.

## Purchase gate

No subscription is approved by this document. Before buying any plan, run a
small overlap pilot and require all of the following:

1. exact identifier matching through ticker history, CIK, LEI or ISIN;
2. point-in-time filing dates and explicit period/unit/currency metadata;
3. source links or enough provenance to reproduce the observation;
4. conflict reporting against SEC or AFM/ESEF rather than silent overwrite;
5. a measured, material increase in reliable metric coverage;
6. acceptable redistribution and public-site terms;
7. provider-neutral import into the existing evidence ledger.

## Recommended future path

1. Keep SEC and AFM/ESEF as primary filed evidence.
2. Trial SimFin against a stratified US gap sample before purchasing Basic.
3. Trial EODHD only if Amsterdam/global coverage or a single-vendor operational
   model becomes more valuable than stronger filing lineage.
4. Purchase the cheapest tier that passes the measured pilot.

## Primary vendor references

- SimFin coverage: <https://www.simfin.com/en/fundamental-data-download/>
- SimFin pricing: <https://www.simfin.com/en/prices/>
- SimFin API client: <https://github.com/SimFin/simfin>
- EODHD pricing: <https://eodhd.com/pricing>
- EODHD Amsterdam exchange: <https://eodhd.com/exchange/AS>
- EODHD exchange API: <https://eodhd.com/financial-apis/exchanges-api-list-of-tickers-and-trading-hours>

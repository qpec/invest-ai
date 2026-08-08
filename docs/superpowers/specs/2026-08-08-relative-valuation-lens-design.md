# Relative Valuation Lens Design

## Purpose

Make the Top 48 show the price Scout actually used and give a non-technical reader a defensible sense of whether the current valuation appears inexpensive, without turning the site into a buy/sell recommender.

## Evidence and decisions

- Scout already has a dated current price for all 48 selected companies. The public thesis projection currently omits that field, so the apparent missing-price problem is a presentation defect.
- All 48 have a computable owner free-cash-flow yield. The selected set is intentionally concentrated in high-yield names, so comparisons must use the full Scout universe rather than only the Top 48.
- Sector-relative comparison is the primary benchmark when the sector label exists and the cohort has at least 20 measured companies. The observed smallest valid cohort is 39 and the median is 186.
- When sector metadata is absent or the cohort is too small, use the full measured Scout universe and label that fallback explicitly.
- Historical self-relative valuation is excluded from this release because the production model does not yet contain a reliable historical owner-cash-yield series.
- No additional quote API is introduced. The existing point-in-time Scout price remains the single source, avoiding rate limits, authentication, and quote-date disagreement.

## Public model

Each accepted reader receives an allowlisted `valuation_lens` object:

```json
{
  "price": 74.12,
  "price_as_of": "2026-08-06",
  "owner_cash_yield_pct": 8.0,
  "owner_cash_multiple_x": 12.5,
  "comparison_scope": "sector",
  "comparison_label": "Information Technology sector",
  "comparison_count": 181,
  "percentile": 93,
  "signal": "Appears inexpensive on current owner cash flow",
  "caveat": "Current cash flow may overstate normalized earning power."
}
```

The price comes from the point-in-time detail bundle, the yield comes from the compact Scout row, and the percentile is calculated against all measured public Scout rows. The multiple is `100 / yield_pct` only for a positive yield. No input dictionary is copied wholesale.

## Signal language

Higher cash yield means a lower valuation relative to current owner cash flow. Percentile bands are deliberately descriptive:

- 80–100: `Appears inexpensive on current owner cash flow`
- 60–79: `Looks somewhat inexpensive on current owner cash flow`
- 40–59: `Sits near the middle on current owner cash flow`
- 20–39: `Looks somewhat demanding on current owner cash flow`
- 0–19: `Appears demanding on current owner cash flow`

The signal never says `cheap stock`, `buy`, `sell`, `upside`, or `fair value`. A visible caveat explains that the indication depends on current owner cash flow being representative. Use the approved thesis bear case first; fall back to a fixed normalization warning when no concise caveat is available.

## Interface

Every Top 48 card shows current price with quote date plus a compact valuation signal. The full reader opens with a dedicated Valuation context panel containing:

1. current price and date;
2. owner-cash yield;
3. the equivalent owner-cash multiple;
4. the relative percentile and named comparison scope;
5. the conditional caveat.

Quality, risk, and valuation stay visually and semantically separate. Missing values render as honest unavailable states rather than invented estimates.

## Integrity and release gates

Publication blocks when any accepted Top 48 reader lacks its point-in-time price, price date, positive owner-cash yield, comparison count, percentile, signal, or caveat. It also blocks on a mismatched symbol or a percentile outside 0–100. Tests cover sector comparison, universe fallback, tied values, signal boundaries, public allowlisting, generated card/reader copy, mobile layout, and all 48 production readers.


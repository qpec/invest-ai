# Draft investment thesis — CROX (Crocs, Inc.)

CROX is in the Scout's top 1%. Write the DRAFT thesis the owner will take to the Gate. You are researching and writing; the owner decides conviction and whether to buy (FR9), and this system never executes trades (FR11).

## What to produce

- `/tmp/claude-0/-home-user-stock-agentcy/db838204-eb06-56a4-a9ca-797d9c9c8009/scratchpad/theses/drafts/CROX/report.md` — the extensive research: business model, moat evidence, owner-earnings history and quality, valuation work anchored on the packet's metrics, competitive landscape, the bear case, and what you could NOT verify
- `/tmp/claude-0/-home-user-stock-agentcy/db838204-eb06-56a4-a9ca-797d9c9c8009/scratchpad/theses/drafts/CROX/summary.md` — one page for a NON-TECHNICAL reader, opening with the heading `## Executive summary`: what the business does, why it might compound, what would make us leave, what it costs to be wrong. No jargon, no ratio without a translation
- `/tmp/claude-0/-home-user-stock-agentcy/db838204-eb06-56a4-a9ca-797d9c9c8009/scratchpad/theses/drafts/CROX/thesis.json` — the structured draft matching the schema below

## How

1. Read the packet below in full — especially the fragility findings.
2. Research the company with your own web tools: competitive landscape, management, recent events, anything the filings and metrics cannot show. Budget roughly 20 searches; depth beats breadth.
3. Write `report.md`, then `summary.md`, then `thesis.json`.
4. Run the validation command below and fix anything it reports.

## Rules

- Every factual claim from research carries a source URL in `sources`.
- The bear case names every severe fragility finding from the packet.
- No conviction, no circle-of-competence, no price target, no buy recommendation — none of those are yours to write.
- If the business cannot be explained in two sentences, say so in the report and let the owner PASS rather than padding the thesis.

## The research packet (both judgements, unmerged)

```

SYMBOL: CROX  (Crocs, Inc. — Consumer Discretionary)
market cap: 6,137,449,051 USD

== The Owner's Scorecard (Buffett: how good is the business) ==
score: 82.0/87 = 94% -> band Exceptional (evidence: full)
  strongest: carried by owner-FCF yield on EV at 9.1% (15.0/15)
  weakest: held back by current ratio at 1.49 (1.5/3)

== The Inversion Layer (Munger: how it breaks) ==
verdict: Ordinary — Normal business risk
  - The price fell 74.9% peak-to-trough (2020-01-06 -> 2020-03-16) and has since regained that peak — volatile, not ruined, but a fall the owner had to sit through.
  - This business resists valuation: annual revenue growth is typically 19 points away from its 18%/yr average and the operating margin is typically 10 points away from its 14% average — what cannot be valued must be avoided however cheap it looks.
severe findings: none.

== Current registry metrics (set trigger thresholds against these) ==
  owner_fcf_margin_pct = 16.4  [% of TTM revenue]
  owner_fcf_yield_pct = 9.1  [% of own EV]
  revenue_growth_pct = 16.3  [%/yr (annual CAGR)]
  roic_pct = 24.3  [% (Greenblatt)]
  gross_margin_pct = 57.5  [% of TTM revenue]
  net_debt_to_ebitda = n/a  [x (TTM)]
  sbc_pct_of_revenue = 1.0  [% of TTM revenue]
  share_count_trend_pct_per_year = -12.0  [%/yr (split-adjusted)]
  accrual_divergence_pct = -4.2  [% of TTM revenue (NI incl NCI - OCF)]
  owner_fcf_usd = 663,103,000.0  [USD (TTM)]

```

## Filings text

```

[filings text skipped by --no-filings]

```

## The framework you must apply (the Constitution)

- **Buffett — what to buy.** Wonderful businesses at fair prices. A moat with EVIDENCE,
  owner earnings (the cash the owner could actually extract) over reported EPS, and the
  10-year test. If the business model and its moat cannot be explained in two sentences,
  say so plainly rather than writing three.
- **Munger — what to avoid.** Inversion: how would this lose the owner's money? Your bear
  case must address, BY NAME, every severe fragility finding in the packet. You may argue
  against one; you may never ignore one.
- **Honesty.** Cite a source for every factual claim from your research. No price targets.
  A weakness stated plainly beats a strength oversold. Ignore cost basis and entry timing
  entirely — the stock does not know what anyone paid.
- **Not yours to decide.** Conviction, circle-of-competence fit, and whether to buy belong
  to the owner at the Gate. The schema has no field for them; do not editorialise them
  into the prose either.

## Trigger discipline (this is the part the machine holds you to)

- At least 3 triggers, of which at least one is `kind: "metric"`.
- A **metric** trigger tests ONE registry metric against a threshold. The registry is
  fixed — see the packet for the metrics, their units, and their current values. No other
  quantity is checkable; do not invent one, and do not reference a metric the packet shows
  as `n/a`.
- An **event** or **narrative** trigger is ONE yes/no question about public information,
  with its evidence standard inside the question. Events are facts (a contract lost, a CEO
  departure). Narratives are judgements, and their `action` MUST be `"review"`.
- **No price-based triggers.** A falling quote with an intact thesis is an opportunity,
  not an invalidation.
- `action: "break"` only where the pre-committed answer is sell. `"review"` where the
  owner should re-examine.
- Metric thresholds should demand persistence (`consecutive_checks` >= 2) unless a single
  reading is genuinely conclusive. Set thresholds against the CURRENT values in the
  packet, so a trigger is neither already-fired nor unreachable.

### The thesis schema (thesis.json)

Write JSON matching this schema exactly. Every listed field is required; no extra fields.

```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string"
    },
    "business_model": {
      "type": "string",
      "description": "Two sentences. If it needs more, PASS."
    },
    "moat": {
      "type": "object",
      "properties": {
        "kind": {
          "type": "string",
          "enum": [
            "network_effects",
            "switching_costs",
            "cost_advantage",
            "brand_trust",
            "regulatory",
            "none"
          ]
        },
        "evidence": {
          "type": "array",
          "items": {
            "type": "string"
          }
        }
      },
      "required": [
        "kind",
        "evidence"
      ],
      "additionalProperties": false
    },
    "owner_earnings_picture": {
      "type": "string"
    },
    "valuation_anchor": {
      "type": "object",
      "properties": {
        "metric": {
          "type": "string"
        },
        "value": {
          "type": [
            "number",
            "null"
          ]
        },
        "statement": {
          "type": "string"
        }
      },
      "required": [
        "metric",
        "value",
        "statement"
      ],
      "additionalProperties": false
    },
    "horizon_years": {
      "type": "integer"
    },
    "ten_year_statement": {
      "type": "string"
    },
    "bear_case": {
      "type": "string",
      "description": "Must address every severe fragility finding by name."
    },
    "triggers": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "kind": {
            "type": "string",
            "enum": [
              "metric",
              "event",
              "narrative"
            ]
          },
          "statement": {
            "type": "string"
          },
          "action": {
            "type": "string",
            "enum": [
              "break",
              "review"
            ]
          },
          "metric": {
            "type": [
              "string",
              "null"
            ]
          },
          "op": {
            "type": [
              "string",
              "null"
            ],
            "description": "One of <, <=, >, >= for metric triggers; null otherwise."
          },
          "threshold": {
            "type": [
              "number",
              "null"
            ]
          },
          "consecutive_checks": {
            "type": [
              "integer",
              "null"
            ]
          },
          "question": {
            "type": [
              "string",
              "null"
            ]
          }
        },
        "required": [
          "id",
          "kind",
          "statement",
          "action",
          "metric",
          "op",
          "threshold",
          "consecutive_checks",
          "question"
        ],
        "additionalProperties": false
      }
    },
    "sources": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "required": [
    "symbol",
    "business_model",
    "moat",
    "owner_earnings_picture",
    "valuation_anchor",
    "horizon_years",
    "ten_year_statement",
    "bear_case",
    "triggers",
    "sources"
  ],
  "additionalProperties": false
}
```


## When you are done

Run `python thesis.py record CROX --theses-dir /tmp/claude-0/-home-user-stock-agentcy/db838204-eb06-56a4-a9ca-797d9c9c8009/scratchpad/theses`. It validates what you wrote and prints any problem it finds. **A non-zero exit means the artifact is not accepted** — fix and re-run; do not report the work as finished until it exits clean.

# The small-cap tranche — low caps get a guaranteed seat at the desk

**Date:** 2026-08-14
**Status:** implemented (owner-directed: "low caps must specifically get a chance")
**Where:** `stock-scout/thesis.py` (`top_symbols`, `DESK_SMALL_CAP_CEILING`,
`DESK_SMALL_CAP_RESERVED_FRACTION`)

## The problem, stated honestly

Nothing in the Scout *scores* a small cap worse for being small. Sector percentiles are
size-neutral, the scorecard's ramps are absolute, and the inversion probes don't read
market cap. And yet, in practice, small caps almost never reached the desk, for two
stacked reasons:

1. **The eligibility floor** (2026-08-08 valuation review, V-6) refuses names under
   $300M market cap or $5 — deliberately, for microcap liquidity, data pathologies and
   delisting risk. That decision stands and is not touched here.
2. **Evidence-tier-first ranking.** `scorecard.rank_key` sorts evidence tier before
   percentage, so a thinly-evidenced name can never outrank a fully-measured one. That
   rule is correct for *presentation* — §4.2's "a percentage of available points silently
   rewards ignorance" argument is real. But small caps systematically carry shorter,
   thinner filing histories, so in an all-cap contest for ~70 desk slots the rule quietly
   becomes a size filter: every work order goes to a large cap with a decade of clean
   XBRL, and a $800M name with six years of filings never consumes one, however good its
   numbers.

The result: eligible small caps ($300M–$2B) were nominally "in the race" while
structurally never winning it.

## The decision

Reserve a tranche of the desk slots for small caps, changing **who competes against
whom** and nothing else:

- `DESK_SMALL_CAP_CEILING = 2e9` — the conventional small-cap boundary.
- `DESK_SMALL_CAP_RESERVED_FRACTION = 0.20` — at least `int(count * 0.20)` of the top-1%
  slots (14 of ~70 today) go to the best-ranked names at or under the ceiling.
- Candidates come from the **same gated pool**: scoreable, past Munger's gate, above the
  V-6 floor. The tranche never changes how a name qualifies, only who it competes
  against for the last slots.
- Ranked by the **same key** (`rank_key`, evidence tier first). The returned list stays
  sorted by that key, so a promoted thin-evidence small cap still *ranks* below every
  fully-measured name — the tranche allocates research budget, it does not touch the
  scorecard's ordering or merge any judgement.
- **A reserve never pads.** Fewer qualifying small caps than reserved slots → they all
  get in and the spare slots fall back to the general ranking. No qualifying small caps →
  the feed is byte-identical to the old behaviour.
- **A missing market cap cannot claim a reserved seat.** The floor's rule ("a row without
  a figure is never silently excluded") still lets such a name compete generally, but a
  guaranteed seat is a positive claim and needs the qualifying figure — "refuse, never
  guess" cuts both ways.
- Promoted names displace the lowest-ranked general members, so the feed size is
  unchanged.

## What was deliberately NOT done

- **The $300M/$5 floor was not lowered.** "Low caps" here means small caps the desk can
  actually own in a 10–15 position portfolio. Sub-$300M microcaps stay excluded for the
  V-6 reasons (liquidity, data pathologies, delisting risk); reopening that is its own
  owner decision, not a side effect of this one.
- **`rank_key` was not changed.** Softening evidence-tier-first ranking would weaken the
  §4.2 argument everywhere (picks, site, presentation) to fix a problem that only exists
  in slot allocation. The fix lives where the problem lives.
- **No size factor entered scoring, the scorecard or inversion.** The decision layer
  stays size-blind; the tranche is desk-feed policy in `top_symbols`, exactly where the
  Hell-No gate and the floor already live.

## Known cost

Widening the feed re-ranks the survivors, so existing drafts re-record once as
INPUTS_CHANGED — the documented, intended cost of a ratified policy change
(`top_symbols` docstring). Membership changes reach the public site on the next
production run.

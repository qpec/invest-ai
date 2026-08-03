# The Inversion Layer — Munger's pillar, finally built

**Status:** design, 2026-08-01; **recalibrated against the full 1,904-name SEC export,
2026-08-02** (§8 records what the first cut got wrong and why). Answers the owner's ask for
*"an additional layer of judgement"*, drawn from `virattt/ai-hedge-fund` (the `nassim_taleb`
and `charlie_munger` agents) and worked out in this repo's philosophy.

---

## 1. The gap

The system has become good at one question and has never asked the other.

The Constitution has three pillars. **Buffett** (what to buy) is now well served: the
scorecard scores quality and price against fixed lines, with a DCF and a Buffett checklist
beside it. **Naval** (keep upgrading) lives in the Study and the decision journal. But
**Munger — what to *avoid*** — exists only as three mechanical tripwires: leverage above
4× EBITDA, owner-FCF negative every period, shares up more than 20%/yr.

That is not what Munger's pillar says. It says *inversion*: "instead of 'how do I succeed?',
ask 'how would I guarantee failure?' — then don't do those things." Three accounting
tripwires are not an inversion. They are a smoke alarm. They fire on companies already
burning; they say nothing about a healthy-looking business whose cash engine collapses every
time the world tilts.

The owner has already run into this twice, in his own words:

- Msg 10, on Cirrus Logic: *"V97 but ~90% of revenue = Apple. Customer concentration the
  model does not see — the classic value-trap question."*
- Msg 60, on Adobe: *"−142 percentage points since 2021 while the quality rank stayed
  good… whoever cannot stand to watch this should not run this philosophy."*

Both are the same failure: the model graded the business and never asked how it breaks.

## 2. What this layer is — and what it deliberately is not

**It does not add points to the scorecard.** Buffett's scorecard says how good a business is;
Munger's lens says how it breaks. Adding a fragility score into the 100 points would let a
high total paper over fragility — the exact trade §1.6 of the scorecard design forbids. They
are different questions and they stay in different columns.

**It does not suppress on its own.** The §4.4 vetoes already suppress, on conditions that are
unambiguous. Inversion is judgement, and judgement informs the owner rather than silently
deleting a name. This layer *names the failure mode* and assigns a verdict; the human decides.
An optional formation gate is offered (§6), off by default, because gating entry would change
rules that a blind walk-forward validated and this layer has no such evidence yet.

**What it produces is the thing the system has never produced: a written answer, per company,
to "how would this lose my money?" — with the evidence attached.**

## 3. The probes

All deterministic, all from data already in hand: ~10 years of weekly prices and up to 19
years of annual filings. Each probe returns a severity (`none` / `caution` / `severe`) and a
sentence naming what it found.

### 3.1 Ruin already demonstrated — *price drawdown*
Deepest peak-to-trough in the weekly total-return series, and **whether it recovered**. A
business that has already fallen 70% has told you what it is capable of. Taleb's point, and the
plainest evidence available.

`severe` past −60% **and still below that peak**; `caution` for a −60% fall that was regained,
or a −40% fall still underwater. Permanence is the whole rung: Munger's ruin is *permanent* loss
of capital, and 65% of this universe has fallen 60% at some point — a quarter of them regained
it. A recovered 70% fall is a volatile compounder, not a ruined business, and it is still a fall
the owner had to sit through.

### 3.2 Return asymmetry — *skew and tail ratio*
From `nassim_taleb.analyze_tail_risk`: the skew of weekly returns, and the ratio of the 95th
percentile gain to the 5th percentile loss. A name whose losses are fatter than its gains is
paying you less than it charges you. `severe` when skew < −0.5 **and** tail ratio < 0.9.

### 3.3 The cash engine breaking — *owner-FCF drawdown*
Deepest peak-to-trough in **annual owner earnings**, over the **last ten fiscal years**, capped
at −100%, and **whether the peak came back**. This is the one that matters most to an owner: the
share price recovering is optional, the cash engine recovering is not. On real data it separates
names the scorecard cannot — Medpace has no finding at all; Cirrus Logic fell 89% from its 2017
peak and regained it by 2025, which is a cyclical engine rather than a broken one.

`severe` when the peak was never regained *and* either the trough went negative or the fall
passed −60%; `caution` for a −60% fall that came back, or a −35% fall still below the peak.

Three rules do the work here and each fixes something the first cut got wrong. The **cap**:
owner-FCF is a signed difference of large numbers, so once the trough crosses zero the
percentage is unbounded — this export's 5th percentile was −1,381%, which is the denominator
talking, not a fall twenty times worse than −60%. The **window**: an engine that broke in 2009
and has run cleanly since is not a broken engine, and the Buffett lens beside it is capped at 8
years for exactly that reason. And **permanence**, as in §3.1.

### 3.4 Stress behaviour — *the two real tests*
Owner-FCF in 2020 (a demand shock) and 2022 (a rate shock) against the prior peak, and whether
that peak came back afterwards. Not a simulation — two occasions on which the world actually
broke, inside the data we hold. A business that kept earning through both has evidence no model
can manufacture.

Permanence matters most here of all: nearly every business on earth earned less in 2020 than in
2019, so scoring the shortfall alone made this probe say *"the cash engine buckled"* for 56% of
the universe — a description of COVID, not of the business.

### 3.5 Predictability — *Munger's own filter*
From `charlie_munger.analyze_predictability`, and using **its own measure**: the *mean absolute
deviation* of annual revenue growth, and of the operating margin, both in points. Munger's rule
is that an unpredictable business cannot be valued, and what cannot be valued must be avoided
regardless of how cheap it looks. This is also the constitution's *"if the thesis needs a
spreadsheet with 47 assumptions, walk away."*

The design first specified a coefficient of variation. It does not survive contact with the
data, for two reasons the reference had already designed around. Both quantities are **signed
and sit on top of zero**, so the ratio measures its denominator rather than its dispersion —
Kenvue's dead-flat revenue line (+0.14%/yr, 2.0 points of spread) reads CV 14.7 and is graded
maximally *un*predictable for being the most forecastable shape there is. And a **squared**
penalty lets one EDGAR tag-switch splice decide the answer: Procter & Gamble's revenue chain
contains a +121% year that never happened as a business event, which a standard deviation turns
into 34 points of "volatility" for a company that grows 3%/yr. Absolute deviation in points
reads 20 — still not zero, because the splice *is* in the data, but survivable.

Lines: revenue `severe` at 0.20, `caution` at 0.10 — the reference's own; margin `severe` at
0.10, `caution` at 0.05.

### 3.6 Financing fragility — *the refinancing wall*
Debt due within twelve months against cash plus one year of owner earnings. `severe` when the
maturity exceeds the resources in hand. Plus **dilution during a drawdown**: a rising share count
while the price sat far below its peak means the owner was diluted at the bottom, which is how
permanent loss actually happens.

EDGAR tags the twelve-month maturity for **66% of these filers**, but the tag is not one of the
19 the observations export carries a series for, so until `pit._DISCLOSURE_CONCEPTS` and
`secsv.DISCLOSURE_TAGS` were added this leg was unmeasurable for **every** name. It now runs for
1,146 of 1,904. The **dilution leg still does not run at all** on an EDGAR-built Bundle: it needs
a split history to restate raw share counts, and no such Bundle carries one, so a 20:1 split and
a rescue issuance read identically. Unmeasured and named, never assumed safe.

### 3.7 Concentration — *flag only*
`ConcentrationRiskPercentage1`, tagged by just 11% of these filers and — the sharper problem —
with a **median disclosure date of 2017-12-30**. It is not merely sparse, it is largely
abandoned, so every flag carries the date it was last tagged. Far too sparse to score.

A tagged value of **exactly 100% is refused**: the tag carries no axis member in this export, so
a single-customer disclosure and the *total* row of a disaggregation table are
indistinguishable, and 51 of the 212 filers that tag it at all tag exactly 1.0. Reading those as
"one customer is 100% of revenue" would be the loudest false finding this probe could make.

Where the tag is absent the layer says so rather than implying the risk is absent — the Cirrus
Logic lesson is that silence here is not safety, and CRUS is precisely a name where it still
bites: it does not tag concentration, its cash engine recovered, and the fourth lens therefore
reads green on a business that was ~90% Apple. §7 owns that gap rather than papering over it.

## 4. The verdict

Severities are counted, never averaged — an average would let a good probe cancel a fatal one,
which is precisely the inversion error.

| Verdict | Rule | Meaning | Share of the export |
|---|---|---|---|
| **Ruinous** | ≥ 3 severe | Has already destroyed owner capital, or is built to | 19% |
| **Fragile** | 2 severe, or ≥ 4 cautions | Clear ways this breaks you | 24% |
| **Ordinary** | at most 1 severe, < 4 cautions | Normal business risk | 38% |
| **Robust** | no severe, no caution | Has been tested and held | 4% |
| **Unknown** | too little evidence | Said out loud, never read as safe | 15% |

The rungs are **calibrated, not assumed**, and that is the substance of the 2026-08-02 pass. The
first cut's `≥ 2 severe` was written on the assumption that probes fire rarely; measured, the six
counting probes fire severe on 2–50% of names each, so two of six is close to certain by
arithmetic. It read Ruinous for 71% of the universe — and, worse, for 68% of the scorecard's
*Exceptional* names against 88% of its lowest band. A two-point spread is a layer saying nothing
while sounding certain. The rungs above run 10% Ruinous in Exceptional to 42% in Pass.

One rule is deliberately not about the rung. **A severe probe always stands.** Thin evidence
collapses Robust and Ordinary to Unknown, but never when a probe actually fired severe — absent
data may refuse to certify safety, it may never delete a finding (§7). For the same reason the
§5 lens never returns green while a severe probe stands, whatever rung the count landed on.

Every verdict carries its failure modes in plain language: *"the cash engine fell 89% from its
peak in 2010 and the price has drawn down 52%; losses are fatter than gains."*

## 5. Where it appears

- **The report and datasheet** gain a fragility column beside the score, and the failure modes
  in the per-name audit. A name can be Exceptional and Fragile at once — that pairing is the
  most useful thing this layer produces, and it must be visible rather than reconciled away.
- **The consensus view** gains a fourth lens. Three lenses currently answer "is this good?" in
  three ways; this one answers "will it survive?", which is the question the other three share
  a blind spot on.

## 6. The optional gate

`--fragility-gate` makes a Ruinous verdict block formation entry. **Off by default.** The v3
entry rules earned their place through a blind walk-forward; this layer has no such evidence,
and switching it on silently would trade a validated rule for a plausible one. Validating it
is the same exercise as before: re-run the walk-forward with the gate on and compare against
the pre-registered criterion.

## 7. What it still cannot see

Lawsuits, regulatory change, a competitor's roadmap, an accounting fraud not yet in the
numbers, a key-person risk, a customer concentration that the filer does not tag. This layer
reads what already happened to the cash and the price. It is inversion with evidence, not
foresight — and where the evidence is thin it returns Unknown rather than a comforting number.

Three gaps are worth naming outright, because each one is a place a reader could mistake silence
for safety:

- **The dilution leg of §3.6 never runs on EDGAR data.** No EDGAR-built Bundle carries a split
  history, and without one a 20:1 split and a rescue issuance are the same number.
- **§3.7 sees 11% of filers, mostly as of 2017.** Cirrus Logic — the case that motivated this
  whole layer — is not among them, and its cash engine recovered, so the fourth lens reads green
  on it. The layer did not solve §1's second example; it named it.
- **Revenue chains carry splices.** §3.5's absolute deviation survives one; it does not remove
  it, and a name whose EDGAR chain is badly spliced will read less predictable than it is.

## 8. What the first cut got wrong

Recorded rather than quietly amended, because the process is the point (the decision journal
judges process separately from outcome). The design of 2026-08-01 was written before the layer
had ever been run across the full export. Run, it read **Ruinous for 71% of 1,904 names** and
separated the scorecard's best band from its worst by two percentage points.

Nothing was wrong with the probes' *questions*. Three things were wrong with their *answers*:

1. **Depth was scored where permanence was meant.** §3.1 said outright that recovery is
   "reported, never scored". On a universe where 65% of names have fallen 60% at some point,
   that makes the probe a description of equities rather than a filter.
2. **Two metrics were the wrong shape for signed quantities** — an unbounded percentage on
   owner-FCF once it crosses zero, and a coefficient of variation on growth that sits on zero.
   Both had already been patched once (a floor on the CV); the patch was the signal.
3. **The verdict rungs were assumed rather than measured**, so probe firing rates and the
   verdict rule multiplied instead of composing.

And two probes were reported as covering 64% and 11% of filers when the number that reached them
was **zero** — the tags exist in EDGAR but not in the 19-tag observations export, and nothing
mapped them. Coverage claimed from the data source rather than measured at the consumer is not
coverage. That one is now a rule: every probe's provenance states what fraction of *this export*
it actually measured.

# The Inversion Layer — Munger's pillar, finally built

**Status:** design, 2026-08-01. Answers the owner's ask for *"an additional layer of
judgement"*, drawn from `virattt/ai-hedge-fund` (the `nassim_taleb` and `charlie_munger`
agents) and worked out in this repo's philosophy.

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
Deepest peak-to-trough in the weekly total-return series, and whether it recovered. A business
that has already fallen 70% has told you what it is capable of. Taleb's point, and the plainest
evidence available. `severe` past −60%, `caution` past −40%.

### 3.2 Return asymmetry — *skew and tail ratio*
From `nassim_taleb.analyze_tail_risk`: the skew of weekly returns, and the ratio of the 95th
percentile gain to the 5th percentile loss. A name whose losses are fatter than its gains is
paying you less than it charges you. `severe` when skew < −0.5 **and** tail ratio < 0.9.

### 3.3 The cash engine breaking — *owner-FCF drawdown*
Deepest peak-to-trough in **annual owner earnings** across the filing history. This is the one
that matters most to an owner: the share price recovering is optional, the cash engine
recovering is not. On real data it separates names the scorecard cannot: Medpace 0%, Cirrus
Logic −89%. `severe` past −60%, `caution` past −35%.

### 3.4 Stress behaviour — *the two real tests*
Owner-FCF in 2020 (a demand shock) and 2022 (a rate shock) against the prior peak. Not a
simulation — two occasions on which the world actually broke, inside the data we hold. A
business that kept earning through both has evidence no model can manufacture.

### 3.5 Predictability — *Munger's own filter*
From `charlie_munger.analyze_predictability`: the coefficient of variation of annual revenue
growth and of operating margin. Munger's rule is that an unpredictable business cannot be
valued, and what cannot be valued must be avoided regardless of how cheap it looks. This is
also the constitution's *"if the thesis needs a spreadsheet with 47 assumptions, walk away."*

### 3.6 Financing fragility — *the refinancing wall*
Debt due within twelve months against cash plus one year of owner earnings (available for 64%
of filers; absent → not scored, never assumed safe). Plus **dilution during a drawdown**: a
rising share count while the price sat far below its peak means the owner was diluted at the
bottom, which is how permanent loss actually happens.

### 3.7 Concentration — *flag only*
`ConcentrationRiskPercentage1` is tagged by just 11% of these filers, far too sparse to score.
Where it exists and is high it is reported as a flag. Where it does not, the layer says so
rather than implying the risk is absent — the Cirrus Logic lesson is that silence here is not
safety. (Its cash-engine drawdown, −89%, catches the same fragility by another route.)

## 4. The verdict

Severities are counted, never averaged — an average would let a good probe cancel a fatal one,
which is precisely the inversion error.

| Verdict | Rule | Meaning |
|---|---|---|
| **Ruinous** | ≥ 2 severe | Has already destroyed owner capital, or is built to |
| **Fragile** | 1 severe, or ≥ 3 cautions | One clear way this breaks you |
| **Ordinary** | 1–2 cautions | Normal business risk |
| **Robust** | no severe, ≤ 0 cautions | Has been tested and held |
| **Unknown** | too little evidence | Said out loud, never read as safe |

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

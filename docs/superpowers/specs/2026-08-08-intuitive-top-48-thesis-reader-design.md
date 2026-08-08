# Intuitive Top 48 Thesis Reader

Date: 2026-08-08
Status: Approved design

## Purpose

The public site contains 48 mechanically accepted theses, but the current interface makes them difficult to discover. The Top 48 table looks like a passive data table, its rows have no visible thesis action, Scout rows open technical detail only, and the full thesis cards appear far below the table. A non-technical visitor can reasonably conclude that no stock-level thesis exists.

Section 2, the Thesis Desk, will become a clear public research experience. It will help a visitor scan the Top 48, open any company, understand the higher-level assessment, and walk through the thesis in plain English. Section 1 remains the full Scout. Section 3 remains the combined model portfolio and monitor.

## Chosen approach

Use an editorial Top 48 card grid with an in-page stock reader.

This approach keeps GitHub Pages static, avoids generating and maintaining 48 separate HTML pages, supports direct links through URL hashes, and provides a focused mobile reading experience. Large inline thesis cards are rejected because they would make the Top 48 page excessively long and difficult to scan.

The public experience is fully English.

## Navigation and information flow

Section 2 opens with the heading **“48 companies worth deeper research.”** It contains:

- a search field;
- a small set of useful filters;
- 48 ranked company cards;
- one focused reader view that replaces the list when a company is opened.

Each card displays:

- rank;
- ticker;
- company name;
- company icon or initials fallback;
- a one-sentence business description;
- quality score and grade;
- risk verdict;
- valuation anchor;
- a visible **“View assessment & thesis”** action.

The complete card is clickable, keyboard-accessible, and has a visible focus state. The explicit action remains present so discoverability never depends on guessing that a card can be clicked.

Opening a company changes the URL to a stable hash such as `#thesis/INMD`. Browser Back and Forward work normally. The reader begins with **“Back to Top 48”** and restores the previous search, filters, and scroll position.

Every Top 48 company in the Scout also receives an explicit thesis action. That action switches to Section 2 and opens the matching reader. Non-Top-48 Scout rows keep their existing technical detail behavior.

## Stock assessment reader

The reader starts with an **At a glance** block that answers four questions:

1. **What is it?** A plain-English description of the business.
2. **How strong is the business?** Quality score and grade with one explanatory sentence.
3. **How can it hurt you?** Risk verdict and the most important fragility.
4. **What does the current valuation imply?** The valuation anchor explained in ordinary language.

The rest of the reader follows this order:

1. **The case in one minute** — a short, balanced synthesis of the evidence.
2. **Business and moat** — how the company earns money and what may protect its returns.
3. **Cash economics** — the owner-earnings evidence with technical metrics translated into plain English.
4. **Valuation** — the anchor, its limitations, and the assumptions that matter.
5. **The bear case** — the clearest loss paths, visually distinct from the positive case.
6. **What would change the thesis?** Existing monitoring triggers rewritten as understandable watch items while preserving their exact underlying conditions.
7. **Sources and full research** — collapsed by default for readers who want the full evidence trail.

Quality and risk remain separate judgments. The interface must not invent a combined buy/sell score or imply investment advice. The opening synthesis explains any tension between business quality, fragility, and valuation.

## Visual and content language

The Top 48 uses a three-column grid on wide screens and one column on mobile. Cards use generous spacing, short sentences, consistent labels, and large tap targets. Company name and description carry equal visual weight to the ticker.

The reader uses a single column with a comfortable maximum width. Section headings use direct questions, including **“Why might this be a strong business?”** and **“What could go wrong?”** Technical terms receive a short contextual explanation.

The public interface removes raw JSON, CLI instructions, production controls, model-runtime language, and internal workflow explanations. These remain available only in operator-facing tools and source artifacts.

Color communicates category:

- quality uses a calm positive accent;
- risk uses warning and danger tones;
- valuation uses neutral treatment;
- no color is labelled or presented as buy or sell advice.

Mobile receives a sticky **“Back to Top 48”** control. Desktop and mobile support keyboard navigation, visible focus, browser history, and direct thesis links.

## Company icons

The build fetches company images by ticker from the generic Financial Modeling Prep image endpoint. Images are fetched during the site build, validated as image content, normalized to an appropriate local format and size, and stored inside the generated Pages artifact.

The browser serves the cached local image. It does not contact the image provider during a pageview. A failed fetch, invalid response, or unavailable logo produces a deterministic initials tile. Logo failure never blocks publication because icons are decorative; thesis or identity failure does block publication.

The image source is isolated behind one fetch interface so it can be replaced if availability or terms change. No API credential is embedded in the site.

## Data model and generation

The 48 accepted thesis records remain the source of truth. During assembly, the site builder joins each accepted thesis to:

- Top 48 rank;
- company identity;
- Scout quality score and grade;
- inversion risk verdict and leading fragility;
- valuation anchor;
- cached logo metadata.

One public model drives both the Top 48 cards and the reader. This prevents list and detail views from disagreeing. The existing public allowlist remains the privacy boundary. Private portfolio fields, owner conviction, account data, quantities, acquisition prices, market values, internal notes, and credentials never enter the public model.

Long research and source sections remain collapsed until requested. The initial Top 48 view must not render 48 full reports into the visible page.

## Release behavior and failures

Publication blocks when:

- any Top 48 company lacks an accepted thesis;
- a thesis ticker and Top 48 identity do not match;
- rank is missing or duplicated;
- a card has no working reader route;
- a reader omits a required assessment section;
- the public model contains a private field;
- the site or production snapshot fails an existing release gate.

A company icon failure produces the initials fallback and is recorded as a non-blocking build result. A corrupted cached image is treated the same way.

The site remains static and read-only. It cannot ratify theses, change the portfolio, execute research, or start monitoring jobs.

## Verification

Automated tests must prove:

- exactly 48 cards render for the accepted Top 48 snapshot;
- every card has a visible thesis action;
- each card and Scout thesis action opens the correct symbol;
- each symbol has a stable direct URL;
- browser Back and Forward restore reader and list state;
- Back to Top 48 restores filters and scroll position;
- every reader contains all required sections;
- quality and risk remain separate;
- raw JSON, CLI controls, internal runtime language, and private fields are absent;
- every icon is a local asset or a working initials fallback;
- missing and invalid remote icons do not block a build;
- missing thesis, identity mismatch, duplicate rank, unsafe data, and broken routes do block a build.

Browser verification covers the complete flow at desktop width and 390 px mobile width, including keyboard focus and direct-link loading. The final generated snapshot must pass the existing production gates and be verified on GitHub Pages by its exact snapshot ID after publication.

## Public API assessment

The public-APIs catalog does not provide a dependency that simplifies the thesis-reader interaction. Generic finance and stock APIs exist, but the current SEC and Scout data remain the authoritative research sources. A generic image endpoint is used only for decorative company icons and is protected by build-time caching and fallback behavior.

## Out of scope

- changing the Scout scoring or inversion methodology;
- generating new thesis evidence;
- combining quality and risk into an investment recommendation;
- ratification or portfolio actions on the public site;
- replacing the existing production scheduler;
- redesigning Section 3 beyond maintaining its current combined portfolio-monitor role.

# Intuitive Top 48 Thesis Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Thesis Desk section 2 into an intuitive English Top 48 card index and accessible stock-level assessment reader, with explicit Scout links and locally cached company icons.

**Architecture:** Extend the existing public site model in `stock-scout/webapp.py` with one allowlisted `reader` projection per accepted Top 48 thesis. Add a focused logo-cache module that downloads images before the otherwise offline site render. Keep the GitHub Pages output static: cards and readers are rendered client-side from one model and routed with `#thesis/<SYMBOL>` hashes.

**Tech Stack:** Python 3.13, pytest, the existing single-file HTML/CSS/JavaScript generator, urllib, GitHub Pages, agent-browser.

---

## File map

- Create `stock-scout/company_logos.py`: fetch, validate, cache, and index decorative ticker logos.
- Create `stock-scout/tests/test_company_logos.py`: isolated HTTP, validation, and fallback tests.
- Modify `stock-scout/webapp.py`: public reader projection, card grid, reader UI, routing, Scout thesis actions, and local logo copying.
- Modify `stock-scout/tests/test_webapp.py`: model, privacy, generated HTML, route-contract, and fallback tests.
- Modify `stock-scout/local_production.py`: synchronize logos before the offline static site write.
- Modify `stock-scout/tests/test_local_production.py`: assert the production adapter passes only local cached logo assets into the renderer.
- Modify `agentcy/production.py`: release validation for Top 48 reader completeness and route uniqueness.
- Modify `tests/test_production.py`: blocking release-gate tests.
- Modify `docs/runbook.md`: document the Top 48 reader, logo cache, and fallback behavior.

### Task 1: Define the public stock-reader projection

**Files:**
- Modify: `stock-scout/webapp.py:226-294`
- Test: `stock-scout/tests/test_webapp.py:35-69`

- [ ] **Step 1: Write failing projection tests**

Add tests that build one accepted draft plus its compact Scout row and details:

```python
def test_public_reader_joins_thesis_and_separate_scout_judgements():
    draft = {
        "symbol": "AAA", "accepted": True,
        "thesis": {
            "business_model": "Makes mission-critical widgets.",
            "moat": {"kind": "switching_costs", "evidence": ["Retention is high."]},
            "owner_earnings_picture": "Cash conversion is strong.",
            "valuation_anchor": {"metric": "owner_fcf_yield_pct", "value": 8.2,
                                 "statement": "The current cash yield is 8.2%."},
            "bear_case": "Demand can contract.",
            "ten_year_statement": "Durability depends on retention.",
            "triggers": [], "sources": ["https://example.com/source"],
        },
        "summary_html": "<p>Balanced summary.</p>",
        "report_html": "<p>Full report.</p>", "triggers": [],
    }
    reader = webapp.public_thesis_reader(
        draft,
        {"s": "AAA", "n": "Alpha Inc", "top": 1, "pct": 91.0,
         "band": "Exceptional", "verdict": "Fragile", "reg": {}},
        {"inv": {"failure_modes": [{"severity": "severe", "detail": "Customer concentration."}]},
         "card": {"why": ["Strong returns."]}},
    )
    assert reader["quality"] == {"score": 91.0, "grade": "Exceptional",
                                  "explanation": "Strong returns."}
    assert reader["risk"]["verdict"] == "Fragile"
    assert reader["risk"]["leading_fragility"] == "Customer concentration."
    assert reader["thesis"]["business_model"] == "Makes mission-critical widgets."

def test_public_reader_refuses_unaccepted_or_mismatched_draft():
    with pytest.raises(ValueError, match="accepted thesis"):
        webapp.public_thesis_reader({"symbol": "AAA", "accepted": False},
                                    {"s": "AAA", "top": 1}, {})
    with pytest.raises(ValueError, match="symbol mismatch"):
        webapp.public_thesis_reader({"symbol": "BBB", "accepted": True, "thesis": {}},
                                    {"s": "AAA", "top": 1}, {})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest stock-scout/tests/test_webapp.py -k public_reader -v`

Expected: FAIL because `public_thesis_reader` does not exist.

- [ ] **Step 3: Implement the minimal allowlisted projection**

Add `PUBLIC_READER_THESIS_FIELDS` and `public_thesis_reader(draft, row, detail)`. Select fields explicitly, take company identity and rank from the Scout row, preserve quality and inversion as separate nested objects, select the first severe or caution failure mode as `leading_fragility`, and include `summary_html`, `report_html`, evaluated triggers, and sources.

The function must raise `ValueError` for unaccepted drafts, symbol mismatch, missing rank, missing business model, or missing valuation statement. It must never copy the input dictionaries wholesale.

- [ ] **Step 4: Join exactly one reader to every Top 48 item**

In `assemble`, construct `readers_by_symbol` from `top_rows`, `drafts_by_symbol`, compact rows, and details. Add each projection to `thesis.readers`, sorted by rank. Preserve `thesis.top` temporarily for backward-compatible tests, then remove its public rendering in Task 4.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest stock-scout/tests/test_webapp.py -k 'public_reader or owner_fields' -v`

Expected: PASS.

```bash
git add stock-scout/webapp.py stock-scout/tests/test_webapp.py
git commit -m "feat: project accepted theses into public stock readers"
```

### Task 2: Add deterministic build-time company-logo caching

**Files:**
- Create: `stock-scout/company_logos.py`
- Create: `stock-scout/tests/test_company_logos.py`

- [ ] **Step 1: Write failing cache tests**

```python
def test_sync_downloads_valid_image_and_writes_index(tmp_path):
    def fetch(url, timeout):
        assert url.endswith("/AAA.png") and timeout == 10
        return 200, "image/png", b"\x89PNG\r\n\x1a\n" + b"x" * 80
    result = company_logos.sync(["AAA"], tmp_path, fetch=fetch)
    assert result == {"AAA": "logos/AAA.png"}
    assert (tmp_path / "logos" / "AAA.png").read_bytes().startswith(b"\x89PNG")

def test_sync_uses_initials_fallback_for_bad_response(tmp_path):
    result = company_logos.sync(
        ["BAD"], tmp_path, fetch=lambda *_: (200, "text/html", b"not an image"))
    assert result == {"BAD": None}

def test_sync_reuses_valid_cached_file_without_network(tmp_path):
    target = tmp_path / "logos" / "AAA.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
    result = company_logos.sync(
        ["AAA"], tmp_path,
        fetch=lambda *_: (_ for _ in ()).throw(AssertionError("network called")))
    assert result["AAA"] == "logos/AAA.png"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest stock-scout/tests/test_company_logos.py -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the cache boundary**

Implement:

```python
LOGO_URL = "https://financialmodelingprep.com/image-stock/{symbol}.png"

def fetch_logo(url: str, timeout: int) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "invest-ai-site/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.headers.get_content_type(), response.read(2_000_001)

def valid_image(content_type: str, payload: bytes) -> bool:
    signatures = {
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/jpeg": (b"\xff\xd8\xff",),
        "image/gif": (b"GIF87a", b"GIF89a"),
        "image/webp": (b"RIFF",),
    }
    return (64 <= len(payload) <= 2_000_000
            and any(payload.startswith(sig) for sig in signatures.get(content_type, ()))

def sync(symbols: Iterable[str], root: Path,
         *, fetch=fetch_logo) -> dict[str, str | None]:
    result = {}
    for symbol in sorted(set(symbols)):
        result[symbol] = _sync_one(symbol, root, fetch=fetch)
    return result
```

Requirements:

- symbols must match `^[A-Z0-9.-]{1,15}$`;
- use a ten-second timeout and a descriptive User-Agent;
- accept PNG, JPEG, GIF, or WebP only when magic bytes agree;
- reject payloads smaller than 64 bytes or larger than 2 MB;
- write with `.tmp` plus atomic replace;
- reuse valid cached files;
- catch per-symbol HTTP, timeout, and validation failures and return `None`;
- never write provider URLs or credentials to the public model.

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest stock-scout/tests/test_company_logos.py -v`

Expected: PASS.

```bash
git add stock-scout/company_logos.py stock-scout/tests/test_company_logos.py
git commit -m "feat: cache company logos for static site builds"
```

### Task 3: Integrate local logos into the production artifact

**Files:**
- Modify: `stock-scout/local_production.py:18-33,273-291`
- Modify: `stock-scout/webapp.py:1899-1935`
- Test: `stock-scout/tests/test_local_production.py:96-128`
- Test: `stock-scout/tests/test_webapp.py:148-190`

- [ ] **Step 1: Write failing integration tests**

Extend the local-production build test to stub `company_logos.sync`, return `{"AAA": "logos/AAA.png"}`, and assert `webapp.write_site` receives that map. Add a `write_site` test that creates a cached source image, passes its map, and asserts the generated artifact contains `docs/data/logos/AAA.png` while the payload contains only `data/logos/AAA.png`.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest stock-scout/tests/test_local_production.py -k public_model -v && uv run pytest stock-scout/tests/test_webapp.py -k logo -v`

Expected: FAIL because no logo-cache arguments exist.

- [ ] **Step 3: Wire logo synchronization before offline rendering**

Add `logo_cache: Path | None = None` to `LocalProductionConfig`, defaulting to `<artifact_root>/company-logo-cache` at use time. In `build_site`, extract the symbols from `model["thesis"]["readers"]`, call `company_logos.sync`, and pass both the returned map and cache root to `webapp.write_site`.

Extend `write_site` with keyword-only `logo_assets` and `logo_cache_root`. Copy only validated files referenced by the map into `docs/data/logos/`. Add `logo` to each reader as the local `data/logos/<file>` path or `None`; no external URL reaches HTML.

- [ ] **Step 4: Run focused tests and commit**

Run: `uv run pytest stock-scout/tests/test_company_logos.py stock-scout/tests/test_local_production.py stock-scout/tests/test_webapp.py -k 'logo or public_model' -v`

Expected: PASS.

```bash
git add stock-scout/local_production.py stock-scout/webapp.py \
  stock-scout/tests/test_local_production.py stock-scout/tests/test_webapp.py
git commit -m "feat: publish locally cached company logos"
```

### Task 4: Replace the hidden thesis table with the editorial Top 48 index

**Files:**
- Modify: `stock-scout/webapp.py:787-835,1454-1518,1786-1814`
- Test: `stock-scout/tests/test_webapp.py:130-191`

- [ ] **Step 1: Write failing generated-page tests**

Update `TestSite._model()` with one reader and assert the generated page contains:

```python
assert "48 companies worth deeper research" in page
assert 'id="thesisSearch"' in page
assert 'id="thesisGrid"' in page
assert "View assessment &amp; thesis" in page
assert 'data-thesis-symbol="AAA"' in page
assert "python thesis.py" not in public_thesis_section(page)
assert "thesisTop" not in page
```

Also assert the initials fallback markup is present when `reader["logo"] is None`.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest stock-scout/tests/test_webapp.py -k 'thesis_index or thesis_card' -v`

Expected: FAIL on the old table and operator-facing Thesis Desk content.

- [ ] **Step 3: Implement card-grid HTML, CSS, and filtering**

Replace the old Top 1% table and draft-card host with:

- title and short explanation;
- search input;
- quality and risk filters populated from reader values;
- result count;
- responsive `.thesis-grid` and `.thesis-card` containers;
- a semantic `<button>` labelled `View assessment & thesis` on every card;
- `<img>` with empty `alt` for decorative logos or a visible initials fallback.

`renderThesisIndex()` filters by ticker, company name, quality grade, and risk verdict. It must preserve the active filters in `state.thesisFilters`.

Remove public desk actions, CLI walkthroughs, JSON editors, agent/model metadata, and raw workflow explanations from Section 2. Do not remove operator behavior from served/local tools outside the public tab.

- [ ] **Step 4: Run focused tests and commit**

Run: `uv run pytest stock-scout/tests/test_webapp.py -k 'thesis or owner_fields' -v`

Expected: PASS.

```bash
git add stock-scout/webapp.py stock-scout/tests/test_webapp.py
git commit -m "feat: add intuitive Top 48 thesis index"
```

### Task 5: Build the accessible assessment reader and hash routing

**Files:**
- Modify: `stock-scout/webapp.py:1426-1585,1570-1635,1786-1814`
- Test: `stock-scout/tests/test_webapp.py`

- [ ] **Step 1: Write failing reader-contract tests**

Assert the generated JavaScript and HTML expose:

- `openThesisReader(symbol, push = true)`;
- `closeThesisReader(push = true)`;
- a reader host with `aria-live="polite"`;
- `Back to Top 48`;
- the seven approved section headings;
- collapsed `Sources and full research` details;
- no combined buy/sell score.

Add a pure Python `validate_reader_model(readers, expected_top)` test that rejects duplicate rank, duplicate symbol, missing required section, mismatched Top 48 membership, or unsafe field names.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest stock-scout/tests/test_webapp.py -k 'reader or direct_route' -v`

Expected: FAIL because reader UI and validation do not exist.

- [ ] **Step 3: Implement the reader**

Render these sections in order:

1. At a glance: business, quality, risk, valuation.
2. The case in one minute.
3. Why might this be a strong business?
4. What do the cash economics say?
5. What does the valuation imply?
6. What could go wrong?
7. What would change the thesis?
8. Sources and full research, collapsed.

Escape all thesis text through `esc`; use only pre-sanitized `summary_html` and `report_html` produced by `md_html`. Render monitor triggers as plain-language watch items while preserving their statement, threshold/question, and action.

- [ ] **Step 4: Implement browser-history and state restoration**

Use `#thesis/<SYMBOL>`. Store list scroll position before opening. On close, restore the previous filters and call `window.scrollTo` after the list render. `route()` must open a direct thesis hash on first load, close on browser Back, and retain existing `#scout` and `#portfolio_monitor` behavior.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest stock-scout/tests/test_webapp.py -k 'reader or route or thesis' -v`

Expected: PASS.

```bash
git add stock-scout/webapp.py stock-scout/tests/test_webapp.py
git commit -m "feat: add plain-English stock assessment reader"
```

### Task 6: Link Top 48 Scout rows directly to their readers

**Files:**
- Modify: `stock-scout/webapp.py:928-949,1005-1130`
- Test: `stock-scout/tests/test_webapp.py`

- [ ] **Step 1: Write the failing Scout-link test**

For a row with `top: 1`, assert the row or its technical detail panel contains a visible `View assessment & thesis` button with `data-thesis-symbol="AAA"`. For a row with `top: None`, assert no thesis action is rendered.

- [ ] **Step 2: Run test and verify RED**

Run: `uv run pytest stock-scout/tests/test_webapp.py -k scout_thesis_action -v`

Expected: FAIL because Scout has no explicit thesis action.

- [ ] **Step 3: Add the action without changing ordinary Scout detail**

Add the explicit action to Top 48 rows and the detail-panel header. Clicking it closes the technical panel, switches to Section 2, and calls `openThesisReader(symbol)`. Preserve normal detail panels for all rows.

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest stock-scout/tests/test_webapp.py -k 'scout or thesis_action or route' -v`

Expected: PASS.

```bash
git add stock-scout/webapp.py stock-scout/tests/test_webapp.py
git commit -m "feat: connect Scout candidates to thesis readers"
```

### Task 7: Add fail-closed reader release gates

**Files:**
- Modify: `agentcy/production.py:37-66`
- Modify: `tests/test_production.py`

- [ ] **Step 1: Write failing release-gate tests**

Add valid input with `thesis.readers` matching all Top 48 members, then parameterize invalid cases:

```python
@pytest.mark.parametrize("mutation,check", [
    ("missing_reader", "top_thesis_readers_complete"),
    ("duplicate_rank", "top_thesis_reader_routes_unique"),
    ("missing_section", "top_thesis_reader_sections_complete"),
])
def test_release_rejects_invalid_public_reader_model(mutation, check):
    readers = [
        {"symbol": "AAA", "rank": 1, "logo": None,
         "thesis": {"business_model": "A", "bear_case": "B",
                    "valuation_anchor": {"statement": "V"}, "triggers": []},
         "quality": {"score": 90, "grade": "Exceptional"},
         "risk": {"verdict": "Ordinary", "leading_fragility": "F"},
         "summary_html": "<p>S</p>", "report_html": "<p>R</p>"},
        {"symbol": "BBB", "rank": 2, "logo": "data/logos/BBB.png",
         "thesis": {"business_model": "A", "bear_case": "B",
                    "valuation_anchor": {"statement": "V"}, "triggers": []},
         "quality": {"score": 89, "grade": "Exceptional"},
         "risk": {"verdict": "Fragile", "leading_fragility": "F"},
         "summary_html": "<p>S</p>", "report_html": "<p>R</p>"},
    ]
    if mutation == "missing_reader":
        readers.pop()
    elif mutation == "duplicate_rank":
        readers[1]["rank"] = 1
    elif mutation == "missing_section":
        readers[1]["thesis"].pop("bear_case")
    model = {"portfolio_monitor": [], "thesis": {"readers": readers}}
    result = production.validate_release(valid_release(public_model=model))
    assert not result.checks[check]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_production.py -k reader -v`

Expected: FAIL because the checks do not exist.

- [ ] **Step 3: Implement structural release checks**

Validate reader count against `top_members`, unique symbols and ranks, route-safe symbols, required public sections, and the existing recursive private-field scan. Logo may be `None` or a relative `data/logos/` path; reject external URLs and path traversal.

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/test_production.py stock-scout/tests/test_webapp.py -v`

Expected: PASS.

```bash
git add agentcy/production.py tests/test_production.py
git commit -m "feat: gate public Top 48 reader completeness"
```

### Task 8: Document, build, and verify the exact production artifact

**Files:**
- Modify: `docs/runbook.md`
- Generated: `docs/index.html`
- Generated: `docs/data/`
- Generated: `production-manifest.json`

- [ ] **Step 1: Update the runbook**

Document Section 2’s public behavior, `#thesis/<SYMBOL>` direct links, the generic logo source, local-cache directory, initials fallback, and the fact that logo failure is non-blocking while thesis-reader incompleteness blocks release.

- [ ] **Step 2: Run focused suites**

Run:

```bash
uv run pytest stock-scout/tests/test_company_logos.py \
  stock-scout/tests/test_webapp.py \
  stock-scout/tests/test_local_production.py \
  tests/test_production.py -v
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the complete regression suite**

Run: `uv run pytest`

Expected: all tests pass with zero failures.

- [ ] **Step 4: Run a complete production snapshot build**

Use the existing local production entry point and current production configuration in manual mode. Expected results:

- 48 Top 48 members;
- 48 accepted thesis readers;
- zero failed thesis evaluations;
- `docs/data/logos/` contains cached images for successful downloads;
- every failed logo has an initials fallback;
- release result is `VALIDATED` before publication.

- [ ] **Step 5: Perform browser verification**

Serve the generated artifact locally and use `/home/openclaw/.local/bin/agent-browser` at desktop and 390 × 844. Verify:

- Section 2 visibly shows cards and buttons without scrolling past workflow text;
- search and filters update the result count;
- card and Scout actions open the correct reader;
- `#thesis/INMD` loads directly;
- Back and Forward work;
- Back to Top 48 restores position;
- reader sections are in the approved order;
- logo and initials fallback both render;
- keyboard focus is visible and every action is reachable;
- no horizontal overflow exists at 390 px.

- [ ] **Step 6: Commit documentation and generated production artifact**

```bash
git add docs/runbook.md docs/index.html docs/data production-manifest.json
git commit -m "feat: publish intuitive Top 48 thesis experience"
```

- [ ] **Step 7: Verify before remote publication**

Run:

```bash
git diff --check HEAD~1..HEAD
git status --short
uv run pytest
```

Expected: diff check clean; only the owner’s pre-existing report change and local `data/`/`var/` remain outside commits; full suite passes.

- [ ] **Step 8: Publish and verify GitHub Pages**

Push `main` using the approved credential route. Poll `https://qpec.github.io/invest-ai/` until the exact new snapshot ID is visible. Then load one direct thesis URL, confirm its symbol and required headings, and rotate or destroy temporary credentials according to the established process.

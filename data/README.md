# data/

Seed data for a local desk, carried in the repo so a fresh clone can screen the
real universe without first rebuilding it.

## `universe.csv` — the security master (7,033 names)

The screening universe: 2,934 curated businesses plus every NYSE / Nasdaq /
NYSE-American filer from the SEC's own ticker+exchange map, one canonical share
class per CIK. Columns: `symbol,name,sector,industry,country,market_cap,exchange,
currency`. Public screening metadata only — the same names and sectors the public
desk site already lists.

Point `SCOUT_UNIVERSE` at this file, or at your own; the universe is
pre-committed by design (FR14), so changing your hunting ground is an explicit
edit rather than something the Scout drifts into.

Regenerate with:

```bash
cd stock-scout && uv run python universe.py --sec-merge
```

(`universe.py` alone builds ~2,900 curated candidates from FinanceDatabase;
`--sec-merge` extends any universe with the SEC map, stdlib only.)

### Why it lives here now

It used to live on a `bot/seed` branch, "deliberately outside the code history",
because a DigitalOcean box fetched it at first boot. That box was retired on
2026-08-08 and the desk is local-first, so a branch nobody fetches was the only
copy of a file every real run needs. It is 0.4 MB next to the ~37 MB of built
site this repo already carries on `main`.

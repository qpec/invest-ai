# vendor/ — code carried over from the stock-agentcy runtime

Chat msg 2: "751 regels pure, geteste wiskunde (scout_grade.py) + de geharde yfinance-laag —
vandaag gevendored naar stock-scout/vendor/."

- `scout_grade.py` — **removed 2026-08-08.** It was a byte-identical copy of
  `agentcy/scout_grade.py` with no importers and no tests: a third copy of rules already
  implemented in `../scoring.py` and ratified in `agentcy/scout_grade.py`, and therefore a
  silent drift hazard rather than a safeguard. Diff scoring rules against
  `agentcy/scout_grade.py`, which is the live ratified original.
- `yf_fetch.py` — the hardened yfinance layer, adapted from `agentcy/fetch/yf.py`: same
  fail-loud config, box-wide flock pacing, rate-limit backoff ladder and empty-is-failure
  validation; adapted only to (a) drop nothing, (b) make the pacing interval configurable
  (`set_pace`) because the scout populate runs at ~0.6 s/call instead of the runtime's 2 s
  (RECONSTRUCTION.md §6.5). This one IS imported, by `populate.py`/`augment.py`/`bt_fetch.py`.

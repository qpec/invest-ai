# vendor/ — code carried over from the stock-agentcy runtime

Chat msg 2: "751 regels pure, geteste wiskunde (scout_grade.py) + de geharde yfinance-laag —
vandaag gevendored naar stock-scout/vendor/."

- `scout_grade.py` — **verbatim reference copy** of `agentcy/scout_grade.py` (the
  owner-ratified Scout v2 Stage-1 grader). It still imports the agentcy archive layer and is
  NOT imported by the pipeline; `../scoring.py` is the decoupled reimplementation that
  supersedes it (live + backtest share it). Kept so every scoring rule can be diffed against
  its ratified origin.
- `yf_fetch.py` — the hardened yfinance layer, adapted from `agentcy/fetch/yf.py`: same
  fail-loud config, box-wide flock pacing, rate-limit backoff ladder and empty-is-failure
  validation; adapted only to (a) drop nothing, (b) make the pacing interval configurable
  (`set_pace`) because the scout populate runs at ~0.6 s/call instead of the runtime's 2 s
  (RECONSTRUCTION.md §6.5). This one IS imported, by `populate.py`/`augment.py`/`bt_fetch.py`.

#!/usr/bin/env bash
set -euo pipefail

symbol="${1:?usage: scout-thesis-runner.sh SYMBOL ABSOLUTE_WORK_ORDER RUN_ID}"
work_order="${2:?usage: scout-thesis-runner.sh SYMBOL ABSOLUTE_WORK_ORDER RUN_ID}"
run_id="${3:?usage: scout-thesis-runner.sh SYMBOL ABSOLUTE_WORK_ORDER RUN_ID}"

if [[ "${work_order}" != /* || ! -f "${work_order}" ]]; then
  echo "work order must be an existing absolute path" >&2
  exit 2
fi

safe_symbol="${symbol//[^A-Za-z0-9_.-]/_}"
safe_run_id="${run_id//[^A-Za-z0-9_.-]/_}"
session_key="agent:nova:scout-thesis-${safe_run_id}-${safe_symbol}"
result_path="$(dirname "${work_order}")/agent-run.json"

prompt="Execute the thesis work order at ${work_order} exactly. Use primary sources and current web research where the work order requires it. Write report.md, summary.md and thesis.json to the paths named by the work order. Do not ratify the thesis and do not send user-facing messages. The production orchestrator will perform the mechanical Gate validation after you finish. Return only a concise completion status after all three files exist."

echo "thesis runner start: ${symbol}"
openclaw agent \
  --agent nova \
  --model openai/gpt-5.6-sol \
  --thinking max \
  --session-key "${session_key}" \
  --timeout 3600 \
  --message "${prompt}" \
  --json >"${result_path}"
echo "thesis runner complete: ${symbol}"

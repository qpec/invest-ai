"""Claude Messages API client on the stdlib — the repo's tg.py pattern, pointed at
Anthropic (THESIS-DESIGN.md §5).

Hand-rolled on urllib for the same reason the Telegram client is: the runtime surface we
need is one endpoint (`POST /v1/messages`), and NFR7 prices every dependency against the
complexity it displaces. The shapes below follow the current API (2026-08): adaptive
thinking is the model's default on claude-opus-5 (no `thinking` parameter is sent, and no
sampling parameters exist to send — `temperature`/`top_p`/`top_k` are rejected there),
`web_search_20260209` is the server-side search tool, and a custom tool with `strict: true`
is how a run returns machine-valid JSON.

Two loop-level facts every caller is built around:

- `stop_reason == "pause_turn"`: a server-tool turn hit its iteration limit. The turn is
  UNFINISHED — append the assistant content and re-send; the server resumes. Treating it
  as final silently truncates a research run.
- `stop_reason == "refusal"`: a safety classifier declined (HTTP 200, not an error).
  `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) is sent by default so a
  false positive re-runs server-side on the recommended fallback model instead of killing
  a batch; pass `fallbacks=None` to opt out. A refusal that survives the fallback chain
  surfaces as RefusalError, never as an empty result.

No streaming: per-request `max_tokens` stays at 16k (under the HTTP-timeout guidance) and
long work arrives across turns via pause_turn/tool_use instead of one giant response.
"""
from __future__ import annotations

import http.client
import json
import os
import random
import ssl
import time
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("AGENTCY_LLM_MODEL", "claude-opus-5")
DEFAULT_MAX_TOKENS = 16000
REQUEST_TIMEOUT = 600           # seconds; a server-tool turn can legitimately run minutes
FALLBACK_BETA = "server-side-fallback-2026-07-01"
OAUTH_BETA = "oauth-2025-04-20"

# The server-side web search tool (dynamic filtering variant, Opus 4.6+/Sonnet 5+).
# `max_uses` is the caller's budget knob; the default is deliberately generous for a
# deep-research run and tight for a monitor check.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_RETRY_DELAY = 60.0          # a server-sent retry-after is honoured but never past this


class LLMError(Exception):
    """Base for everything this module raises."""


class APIStatusError(LLMError):
    def __init__(self, status: int, body: str):
        self.status, self.body = status, body
        super().__init__(f"HTTP {status}: {body[:400]}")


class RefusalError(LLMError):
    """The whole request (including any fallback chain) was declined. Carries the
    category so the caller can say WHY a thesis could not be written."""

    def __init__(self, category, explanation):
        self.category, self.explanation = category, explanation
        super().__init__(f"refused (category={category}): {explanation or 'no explanation'}")


class NoAPIKeyError(LLMError):
    """No credential in the environment. Callers surface this as 'unchecked', loudly —
    the monitor must never let a missing key read as an intact thesis."""


def _credentials() -> dict:
    """Auth headers from the environment: ANTHROPIC_API_KEY (x-api-key) first, else
    ANTHROPIC_AUTH_TOKEN (Bearer + the oauth beta header)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return {"x-api-key": key}
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}", "_oauth": "1"}
    raise NoAPIKeyError("set ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN)")


class HttpTransport:
    """POST one Messages payload, with retry on the retryable statuses. Kept tiny and
    stateful-less so tests replace it with a scripted fake (the suite is offline)."""

    def __init__(self, url: str = API_URL, timeout: int = REQUEST_TIMEOUT,
                 max_retries: int = 4):
        self.url, self.timeout, self.max_retries = url, timeout, max_retries
        self.context = ssl.create_default_context()

    def __call__(self, payload: dict, betas: tuple = ()) -> dict:
        creds = _credentials()
        headers = {"content-type": "application/json", "anthropic-version": API_VERSION}
        beta_values = [b for b in betas if b]
        if creds.pop("_oauth", None):
            beta_values.append(OAUTH_BETA)
        if beta_values:
            headers["anthropic-beta"] = ",".join(beta_values)
        headers.update(creds)
        body = json.dumps(payload).encode("utf-8")

        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(self.url, data=body, headers=headers,
                                             method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout,
                                            context=self.context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                text = error.read().decode("utf-8", "replace")
                if error.code not in RETRYABLE_STATUS or attempt == self.max_retries:
                    raise APIStatusError(error.code, text) from None
                # A server-sent retry-after is honoured but CAPPED: an 86400 from a proxy
                # must not put a monitor run to sleep for a day. int() rather than
                # isdigit()+float() because unicode digits pass isdigit and crash float.
                try:
                    delay = float(int(error.headers.get("retry-after", "")))
                except (TypeError, ValueError):
                    delay = 2.0 ** attempt + random.random()
                delay = min(delay, MAX_RETRY_DELAY)
                last = APIStatusError(error.code, text)
            except (urllib.error.URLError, TimeoutError, OSError,
                    http.client.HTTPException, json.JSONDecodeError) as error:
                if attempt == self.max_retries:
                    raise LLMError(f"network failure: {error}") from error
                delay = min(2.0 ** attempt + random.random(), MAX_RETRY_DELAY)
                last = error
            time.sleep(delay)
        raise LLMError(f"retries exhausted: {last}")


class Usage:
    """Accumulated token spend across a run, priced so every artifact can carry its own
    cost. Prices are opus-5 launch prices in USD/MTok and are labelled an ESTIMATE."""

    PRICES = {"claude-opus-5": (5.00, 25.00)}

    def __init__(self, model: str):
        self.model = model
        self.input_tokens = self.output_tokens = 0
        self.cache_read = self.cache_write = 0
        self.turns = 0

    def add(self, usage: dict):
        self.turns += 1
        self.input_tokens += usage.get("input_tokens") or 0
        self.output_tokens += usage.get("output_tokens") or 0
        self.cache_read += usage.get("cache_read_input_tokens") or 0
        self.cache_write += usage.get("cache_creation_input_tokens") or 0

    def estimated_cost(self) -> float | None:
        prices = self.PRICES.get(self.model)
        if not prices:
            return None
        in_price, out_price = prices
        return ((self.input_tokens + self.cache_write * 1.25 + self.cache_read * 0.1)
                * in_price + self.output_tokens * out_price) / 1_000_000

    def as_dict(self) -> dict:
        return {"model": self.model, "turns": self.turns,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cache_read_input_tokens": self.cache_read,
                "cache_creation_input_tokens": self.cache_write,
                "estimated_cost_usd": self.estimated_cost()}


class Client:
    """The one loop every LLM feature in this repo runs on: converse until the model
    either calls the caller's strict tool or ends the turn, resuming pause_turn and
    surfacing refusals as errors rather than empty results."""

    def __init__(self, transport=None, model: str = DEFAULT_MODEL,
                 fallbacks: str | None = "default", max_turns: int = 12):
        self.transport = transport or HttpTransport()
        self.model = model
        self.fallbacks = fallbacks
        self.max_turns = max_turns

    def _request(self, messages: list, *, system: str, tools: list,
                 tool_choice: dict | None, max_tokens: int) -> dict:
        payload = {"model": self.model, "max_tokens": max_tokens,
                   "system": system, "messages": messages}
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        betas = ()
        if self.fallbacks:
            payload["fallbacks"] = self.fallbacks
            betas = (FALLBACK_BETA,)
        return self.transport(payload, betas=betas)

    def run(self, *, system: str, user: str, tools: list, capture_tool: str,
            max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
        """Run the agentic loop. Returns
        {"captured": <tool input or None>, "text": <joined text turns>,
         "usage": <Usage.as_dict()>, "stop_reason": <final>}.

        `capture_tool` is the caller's strict tool name; the FIRST call to it ends the
        loop and its input is the structured result. Server tools (web_search) run on
        Anthropic's side and never surface as client tool_use blocks."""
        usage = Usage(self.model)
        messages: list = [{"role": "user", "content": user}]
        texts: list[str] = []
        stop_reason = None

        for _ in range(self.max_turns):
            response = self._request(messages, system=system, tools=tools,
                                     tool_choice=None, max_tokens=max_tokens)
            usage.add(response.get("usage") or {})
            stop_reason = response.get("stop_reason")
            content = response.get("content") or []

            for block in content:
                if block.get("type") == "text" and block.get("text"):
                    texts.append(block["text"])

            if stop_reason == "refusal":
                details = response.get("stop_details") or {}
                raise RefusalError(details.get("category"), details.get("explanation"))

            if stop_reason == "pause_turn":
                # Unfinished server-tool turn: append and re-send; the server resumes.
                messages.append({"role": "assistant", "content": content})
                continue

            if stop_reason == "tool_use":
                captured = next((b for b in content if b.get("type") == "tool_use"
                                 and b.get("name") == capture_tool), None)
                if captured is not None:
                    return {"captured": captured.get("input"), "text": "\n\n".join(texts),
                            "usage": usage.as_dict(), "stop_reason": stop_reason}
                # A tool_use for a tool we don't run client-side (should not happen:
                # web_search is server-side). Refuse the call so the loop cannot hang.
                refusals = [{"type": "tool_result", "tool_use_id": block["id"],
                             "content": "This tool is not available client-side.",
                             "is_error": True}
                            for block in content if block.get("type") == "tool_use"]
                if not refusals:
                    # tool_use with zero tool_use blocks: malformed; an empty-content
                    # user message would 400. Surface it as an unfinished run instead.
                    return {"captured": None, "text": "\n\n".join(texts),
                            "usage": usage.as_dict(), "stop_reason": stop_reason}
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": refusals})
                continue

            # end_turn / max_tokens: the model finished without calling the tool.
            return {"captured": None, "text": "\n\n".join(texts),
                    "usage": usage.as_dict(), "stop_reason": stop_reason}

        raise LLMError(f"no result after {self.max_turns} turns "
                       f"(last stop_reason={stop_reason})")

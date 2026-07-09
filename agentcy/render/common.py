"""Shared render helpers: the ONE HTML escaper, <pre>/fenced tables, verbatim template
constants, and Europe/Amsterdam date labels (display tz applied only at render time)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_AMS = ZoneInfo("Europe/Amsterdam")
_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def esc(s: str) -> str:
    """The one HTML escaper: & < > (parse_mode=HTML, locked). & first, always."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pre_table(rows, *, header=None, skin: str = "html") -> str:
    """Monospace table. HTML skin -> escaped <pre> block; markdown skin -> fenced block.
    Every column space-padded to its widest cell so rows align in a monospace font."""
    body = list(rows)
    grid = ([list(header)] + [list(r) for r in body]) if header is not None else [list(r) for r in body]
    ncols = max((len(r) for r in grid), default=0)
    widths = [0] * ncols
    for r in grid:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt(r):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip() \
            .ljust(sum(widths) + 2 * (ncols - 1))

    lines = [fmt(r) for r in grid]
    text = "\n".join(lines)
    if skin == "md":
        return "```\n" + text + "\n```"
    return "<pre>" + esc(text) + "</pre>"


def split_4096(text: str, *, limit: int = 4096) -> list[str]:
    """Split an HTML message into <=limit-char paragraphs on blank-line boundaries,
    then on single newlines, then hard-cut — a paragraph is never torn mid-tag when a
    boundary exists. Used by the outbox/daemon before send; single output when it fits."""
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        piece = (buf + "\n\n" + para) if buf else para
        if len(piece) <= limit:
            buf = piece
            continue
        if buf:
            out.append(buf)
            buf = ""
        if len(para) <= limit:
            buf = para
            continue
        # oversize single paragraph: split on newlines, then hard-cut
        cur = ""
        for line in para.split("\n"):
            p2 = (cur + "\n" + line) if cur else line
            if len(p2) <= limit:
                cur = p2
            else:
                if cur:
                    out.append(cur)
                while len(line) > limit:
                    out.append(line[:limit])
                    line = line[limit:]
                cur = line
        if cur:
            buf = cur
    if buf:
        out.append(buf)
    return out


def ams_date_label(dt: datetime) -> str:
    """'Wed 8 Jul 2026' in Europe/Amsterdam."""
    d = dt.astimezone(_AMS)
    return f"{_WD[d.weekday()]} {d.day} {_MON[d.month - 1]} {d.year}"


def ams_datetime_label(dt: datetime) -> str:
    """'Wed 8 Jul 2026, 07:00 CET' in Europe/Amsterdam (label 'CET' fixed per G.1 wording)."""
    d = dt.astimezone(_AMS)
    return f"{ams_date_label(dt)}, {d:%H:%M} CET"


# --- Mandatory verbatim fragments (template constants; lint asserts presence) --------
WHAT_THIS_IS_NOT = (
    "WHAT THIS IS NOT: not a price alarm. The stock is {pct} this month; that is not\n"
    "why you are reading this and it plays no part in what follows. Cost basis is\n"
    "not shown and will not be considered."
)
INVITATION_CLOSER = "this is an invitation, not an instruction."
DEGRADED_LINE = "Nothing is wrong; I just can't see."
DEADLINE_FRAMING = "decision by {date} ({n} days)"
INDEXING_EXIT_CLAUSE = (
    "If trailing-36m ever shows the index persistently ahead of a clean process, the "
    "honest conclusion changes to indexing — that is what this report exists to detect."
)

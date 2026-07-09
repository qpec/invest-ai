import dataclasses
import pytest
from agentcy.render import contexts as C


def _fields(cls):
    return {f.name for f in dataclasses.fields(cls)}


def test_all_contexts_are_frozen():
    for name in ("DailyContext", "WeeklyContext", "AlertContext", "AlertItemContext",
                 "EventContext", "QuarterlyContext", "StatusContext", "GateContext",
                 "StudyContext", "HeaderBlock", "OpportunityLine", "OpenLoopLine",
                 "PortfolioRow", "DecisionBlock", "RenderedOutput"):
        cls = getattr(C, name)
        assert cls.__dataclass_params__.frozen, f"{name} must be frozen"


def test_daily_and_status_have_no_euro_benchmark_or_costbasis_fields():
    # invariant 4 + 7 + FS-F8 as structure: a template author cannot reference what does not exist.
    banned = {"benchmark", "cost_basis", "avg_open_price", "pnl", "p_l", "value_eur",
              "cash_eur", "total_eur", "mv_eur"}
    for cls in (C.DailyContext, C.StatusContext, C.HeaderBlock, C.OpportunityLine):
        assert _fields(cls).isdisjoint(banned), f"{cls.__name__} exposes a banned field"


def test_only_quarterly_carries_benchmark_and_records():
    assert {"honest_question", "records_appendix"} <= _fields(C.QuarterlyContext)
    for cls in (C.DailyContext, C.WeeklyContext, C.AlertContext, C.EventContext, C.StatusContext):
        assert "records_appendix" not in _fields(cls)
        assert "benchmark" not in _fields(cls)


def test_weekly_carries_value_but_no_benchmark_or_costbasis():
    f = _fields(C.WeeklyContext)
    assert "total_eur" in f                       # §15 A3: weekly carries EUR value
    assert "benchmark" not in f and "cost_basis" not in f


def test_rendered_output_defaults():
    r = C.RenderedOutput(telegram_html="x", markdown="x", output_class="daily")
    assert r.owner_spans == () and r.ask_id is None and r.reply_markup_json is None

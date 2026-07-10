"""FR9 structurally: conviction/mgmt_trust/circle_fit/ten_year_statement have NO flag path
anywhere in the parser tree, and --json exists only on output surfaces (tech-arch §10/§13)."""
import argparse

FORBIDDEN = {
    "--conviction", "--mgmt-trust", "--mgmt_trust", "--circle-fit", "--circle_fit",
    "--ten-year-statement", "--ten_year_statement", "--ten-year",
}
JSON_ALLOWED = {("thesis", "show"), ("ask", "list"), ("watchlist", "list")}


def _walk(parser, path=()):
    """Yield (path, option_strings) for every action in the whole subparser tree."""
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sub in a.choices.items():
                yield from _walk(sub, path + (name,))
        elif a.option_strings:
            yield path, tuple(a.option_strings)


def test_fr9_fields_have_no_flag_path():
    from agentcy.cli import build_parser
    for _path, opts in _walk(build_parser()):
        assert not (set(opts) & FORBIDDEN), f"FR9 breach: {opts}"


def test_json_only_on_output_surfaces():
    from agentcy.cli import build_parser
    for path, opts in _walk(build_parser()):
        if "--json" in opts:
            assert path in JSON_ALLOWED, f"--json on non-output surface {path}"


def test_no_stdin_json_input_flag_anywhere():
    from agentcy.cli import build_parser
    for _path, opts in _walk(build_parser()):
        assert "--from-json" not in opts and "--stdin" not in opts

"""Command-line interface: ``lookml-conformance <command>``."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path

from lookml_conformance import __version__
from lookml_conformance.cases import Case, SuiteError, load_cases
from lookml_conformance.catalog import render_catalog
from lookml_conformance.citations import check_citations
from lookml_conformance.environments import SetupError, setup
from lookml_conformance.judge import Verdict
from lookml_conformance.runner import AdapterSpec, RegistryError, load_registry, run_suite, select_adapters
from lookml_conformance.scorecard import Scorecard, render_markdown, render_text
from lookml_conformance.site import build_site_data, render_site_data

EXIT_OK, EXIT_FAILURES, EXIT_USAGE = 0, 1, 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (SuiteError, RegistryError, SetupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lookml-conformance", description="Run the LookML conformance suite against LookML tools."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--cases", type=Path, default=Path("cases"), help="cases directory (default: ./cases)"
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    list_cmd = commands.add_parser("list", help="list the cases")
    list_cmd.add_argument("--only", metavar="TEXT", help="only cases whose id contains TEXT")
    list_cmd.set_defaults(handler=cmd_list)

    validate = commands.add_parser("validate", help="check every case file against the case format")
    validate.set_defaults(handler=cmd_validate)

    run = commands.add_parser(
        "run",
        help="run adapters against the cases",
        description="Run adapters against the cases. Exits with 1 if any applicable case fails or errors.",
    )
    source = run.add_mutually_exclusive_group()
    source.add_argument(
        "--registry",
        type=Path,
        default=Path("adapters.json"),
        help="adapter registry (default: ./adapters.json)",
    )
    source.add_argument(
        "--command",
        dest="adapter_command",
        metavar="CMD",
        help="run this adapter command instead of the registry, e.g. "
        "'python -m lookml_conformance.adapters.datahub'",
    )
    run.add_argument("--name", default="local", help="adapter name reported for --command (default: local)")
    run.add_argument(
        "--adapter",
        action="append",
        default=[],
        metavar="NAME",
        help="only run this registry adapter (repeatable)",
    )
    run.add_argument("--only", metavar="TEXT", help="only cases whose id contains TEXT")
    run.add_argument(
        "--jobs", "-j", type=int, default=os.cpu_count() or 1, help="adapter processes in parallel"
    )
    run.add_argument("--json", type=Path, metavar="PATH", help="write the scorecard as JSON")
    run.add_argument("--markdown", type=Path, metavar="PATH", help="write the scorecard as Markdown")
    run.add_argument("--quiet", "-q", action="store_true", help="do not print a line per case")
    run.set_defaults(handler=cmd_run)

    report = commands.add_parser("report", help="render a JSON scorecard as Markdown")
    report.add_argument("scorecard", type=Path)
    report.add_argument(
        "--registry",
        type=Path,
        default=Path("adapters.json"),
        help="registry used for tool labels, if present",
    )
    report.set_defaults(handler=cmd_report)

    catalog = commands.add_parser("catalog", help="write CASES.md from the case files")
    catalog.add_argument("--output", "-o", type=Path, default=Path("CASES.md"), help="default: ./CASES.md")
    catalog.add_argument("--check", action="store_true", help="exit with 1 if the file is out of date")
    catalog.set_defaults(handler=cmd_catalog)

    citations = commands.add_parser(
        "check-citations", help="check that every quote still appears on the page it cites (needs network)"
    )
    citations.set_defaults(handler=cmd_check_citations)

    setup_cmd = commands.add_parser(
        "setup", help="install the tool versions from the registry into .envs/ (needs uv or venv, and npm)"
    )
    setup_cmd.add_argument("adapters", nargs="*", metavar="NAME", help="adapters to set up (default: all)")
    setup_cmd.add_argument("--registry", type=Path, default=Path("adapters.json"))
    setup_cmd.add_argument(
        "--python", default="python3", help="interpreter for the Python tools (default: python3)"
    )
    setup_cmd.set_defaults(handler=cmd_setup)

    site = commands.add_parser("site", help="write the website data from the cases and a JSON scorecard")
    site.add_argument("scorecard", type=Path, nargs="?", default=Path("results/latest.json"))
    site.add_argument("--registry", type=Path, default=Path("adapters.json"))
    site.add_argument(
        "--output", "-o", type=Path, default=Path("site/data.json"), help="default: site/data.json"
    )
    site.add_argument("--check", action="store_true", help="exit with 1 if the file is out of date")
    site.set_defaults(handler=cmd_site)
    return parser


def cmd_list(args: argparse.Namespace) -> int:
    for case in load_cases(args.cases, args.only):
        print(f"{case.id:56} {case.status.value:11} {case.title}")
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    print(f"{len(cases)} cases are valid")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases, args.only)
    if not cases:
        print("error: no cases selected", file=sys.stderr)
        return EXIT_USAGE
    adapters = _adapters_for(args)

    def progress(case: Case, adapter: AdapterSpec, verdict: Verdict) -> None:
        if not args.quiet:
            reasons = "; ".join(verdict.reasons)
            print(
                f"{verdict.outcome.value:5} {case.id:56} {adapter.name:20} {reasons[:160]}", file=sys.stderr
            )

    scorecard = run_suite(cases, adapters, jobs=args.jobs, progress=progress)
    print(render_text(scorecard), end="")
    labels = {adapter.name: adapter.display_name for adapter in adapters}
    if args.json:
        _write(args.json, json.dumps(scorecard.to_dict(), indent=2) + "\n")
    if args.markdown:
        _write(args.markdown, render_markdown(scorecard, labels))
    return EXIT_FAILURES if scorecard.failed else EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    scorecard = Scorecard.from_dict(json.loads(args.scorecard.read_text(encoding="utf-8")))
    labels = {}
    if args.registry.is_file():
        labels = {adapter.name: adapter.display_name for adapter in load_registry(args.registry)}
    print(render_markdown(scorecard, labels), end="")
    return EXIT_OK


def cmd_catalog(args: argparse.Namespace) -> int:
    rendered = render_catalog(load_cases(args.cases), cases_path=args.cases.as_posix())
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if current != rendered:
            print(f"{args.output} is out of date; run: lookml-conformance catalog", file=sys.stderr)
            return EXIT_FAILURES
        return EXIT_OK
    _write(args.output, rendered)
    return EXIT_OK


def cmd_check_citations(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    problems = check_citations(cases)
    for problem in problems:
        print(f"{problem.case_id}: {problem.reason}\n  {problem.url}\n  > {problem.quote}")
    total = sum(len(case.citations) for case in cases)
    print(f"{total - len(problems)} of {total} citations found")
    return EXIT_FAILURES if problems else EXIT_OK


def cmd_setup(args: argparse.Namespace) -> int:
    adapters = load_registry(args.registry)
    if args.adapters:
        adapters = select_adapters(adapters, args.adapters)
    setup(adapters, root=args.registry.parent.resolve(), python=args.python)
    return EXIT_OK


def cmd_site(args: argparse.Namespace) -> int:
    scorecard = Scorecard.from_dict(json.loads(args.scorecard.read_text(encoding="utf-8")))
    try:
        data = build_site_data(load_cases(args.cases), scorecard, load_registry(args.registry))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    rendered = render_site_data(data)
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if current != rendered:
            print(f"{args.output} is out of date; run: lookml-conformance site", file=sys.stderr)
            return EXIT_FAILURES
        return EXIT_OK
    _write(args.output, rendered)
    return EXIT_OK


def _adapters_for(args: argparse.Namespace) -> list[AdapterSpec]:
    if args.adapter_command:
        return [AdapterSpec(name=args.name, command=tuple(shlex.split(args.adapter_command)))]
    adapters = load_registry(args.registry)
    return select_adapters(adapters, args.adapter) if args.adapter else adapters


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)

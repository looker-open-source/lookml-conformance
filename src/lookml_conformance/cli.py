# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
from lookml_conformance.adapter import ENTRY_POINT_GROUP, installed_adapters
from lookml_conformance.cases import Case, SuiteError, load_cases
from lookml_conformance.catalog import render_catalog
from lookml_conformance.citations import check_citations
from lookml_conformance.environments import SetupError, setup
from lookml_conformance.judge import Outcome, Verdict
from lookml_conformance.runner import AdapterSpec, RegistryError, load_registry, run_suite, select_adapters
from lookml_conformance.scaffold import adapter_template, class_name, module_name
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
    _add_adapter_selection(run)
    run.add_argument("--json", type=Path, metavar="PATH", help="write the scorecard as JSON")
    run.add_argument("--markdown", type=Path, metavar="PATH", help="write the scorecard as Markdown")
    run.add_argument("--quiet", "-q", action="store_true", help="do not print a line per case")
    run.set_defaults(handler=cmd_run)

    check = commands.add_parser(
        "check-adapter",
        help="check that an adapter's output follows the protocol on every case",
        description="Run adapters on every case and report output that does not follow the protocol. "
        "Case failures are expected and do not count. Exits with 1 if any case produced no usable output.",
    )
    _add_adapter_selection(check)
    check.set_defaults(handler=cmd_check_adapter)

    adapters = commands.add_parser("adapters", help="list the adapters in the registry and those installed")
    adapters.add_argument("--registry", type=Path, default=Path("adapters.json"))
    adapters.set_defaults(handler=cmd_adapters)

    new = commands.add_parser("new-adapter", help="write a starting point for a new Python adapter")
    new.add_argument("name", help="adapter name: lowercase letters, digits and hyphens, e.g. my-tool")
    new.add_argument("--distribution", help="installed package of the tool, for its version (default: NAME)")
    new.add_argument("--output", "-o", type=Path, help="file to write (default: see the command output)")
    new.set_defaults(handler=cmd_new_adapter)

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

    scorecard = run_suite(cases, adapters, jobs=args.jobs, batch=not args.no_batch, progress=progress)
    print(render_text(scorecard), end="")
    labels = {adapter.name: adapter.display_name for adapter in adapters}
    if args.json:
        _write(args.json, json.dumps(scorecard.to_dict(), indent=2) + "\n")
    if args.markdown:
        _write(args.markdown, render_markdown(scorecard, labels))
    return EXIT_FAILURES if scorecard.failed else EXIT_OK


def cmd_check_adapter(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases, args.only)
    adapters = _adapters_for(args)
    scorecard = run_suite(cases, adapters, jobs=args.jobs, batch=not args.no_batch)
    errors = [(result.case_id, name, verdict) for result, name, verdict in scorecard.failures()
              if verdict.outcome is Outcome.ERROR]  # fmt: skip
    for case_id, name, verdict in errors:
        print(f"{name} {case_id}: {'; '.join(verdict.reasons)}")
    for run in scorecard.adapters:
        tally = scorecard.tally(run.name)
        version = run.version or "no version reported (set distribution)"
        print(f"{run.name}: {tally.passed} of {tally.applicable} applicable cases pass; version: {version}")
    if errors:
        print(f"{len(errors)} case runs produced no usable output; see docs/adapter-protocol.md")
        return EXIT_FAILURES
    print(f"the output follows the protocol on all {len(cases)} cases")
    return EXIT_OK


def cmd_adapters(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry) if args.registry.is_file() else []
    root = args.registry.parent
    for adapter in registry:
        executable = Path(adapter.command[0])
        ready = not ("/" in adapter.command[0] and not (root / executable).exists())
        status = "ready" if ready else f"not set up; run: lookml-conformance setup {adapter.name}"
        print(f"{adapter.name:24} registry     {status}")
    for name, entry_point in sorted(installed_adapters().items()):
        print(f"{name:24} entry point  {entry_point.value}")
    if not registry and not installed_adapters():
        print("no adapters found")
    return EXIT_OK


def cmd_new_adapter(args: argparse.Namespace) -> int:
    in_repo = Path("src/lookml_conformance/adapters")
    output = args.output or (in_repo if in_repo.is_dir() else Path()) / f"{module_name(args.name)}.py"
    if output.exists():
        print(f"error: {output} already exists", file=sys.stderr)
        return EXIT_USAGE
    try:
        source = adapter_template(args.name, args.distribution, output.as_posix())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    _write(output, source)
    print(
        f"Next:\n"
        f"  1. Fill in resolve() in {output} (docs/adapter-protocol.md describes the output).\n"
        f'  2. Check it: lookml-conformance check-adapter --command "python {output}"\n'
        f'  3. Score it: lookml-conformance run --command "python {output}" --name {args.name}\n'
        f"  4. To run it by name, add it to adapters.json or register an entry point:\n"
        f'     [project.entry-points."{ENTRY_POINT_GROUP}"]\n'
        f'     {args.name} = "<your module>:{class_name(args.name)}"'
    )
    return EXIT_OK


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


def _add_adapter_selection(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
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
        help="run this adapter command instead of the registry, "
        "e.g. 'python -m lookml_conformance.adapters.datahub'",
    )
    parser.add_argument(
        "--name", default="local", help="adapter name reported for --command (default: local)"
    )
    parser.add_argument(
        "--adapter",
        action="append",
        default=[],
        metavar="NAME",
        help="run this adapter from the registry, or one installed as an entry point (repeatable)",
    )
    parser.add_argument("--only", metavar="TEXT", help="only cases whose id contains TEXT")
    parser.add_argument(
        "--jobs", "-j", type=int, default=os.cpu_count() or 1, help="adapter processes in parallel"
    )
    parser.add_argument(
        "--no-batch",
        action="store_true",
        help="start one adapter process per project (slower, fully isolated)",
    )


def _adapters_for(args: argparse.Namespace) -> list[AdapterSpec]:
    """The adapters to run: a --command, the named --adapter entries, or the whole registry."""
    if args.adapter_command:
        return [AdapterSpec(name=args.name, command=tuple(shlex.split(args.adapter_command)))]
    registry = load_registry(args.registry) if args.registry.is_file() else []
    if not args.adapter:
        if not registry:
            raise RegistryError(f"{args.registry} not found; pass --adapter NAME or --command CMD")
        return registry
    by_name = {adapter.name: adapter for adapter in registry}
    installed = installed_adapters()
    if unknown := [name for name in args.adapter if name not in by_name and name not in installed]:
        known = ", ".join(by_name) or "none"
        raise RegistryError(
            f"unknown adapter(s) {', '.join(unknown)}; in {args.registry}: {known}; "
            f"installed: {', '.join(sorted(installed)) or 'none'}"
        )
    return [by_name.get(name) or installed_adapter_spec(name) for name in args.adapter]


def installed_adapter_spec(name: str) -> AdapterSpec:
    """Run an adapter installed as an entry point, with this interpreter."""
    return AdapterSpec(name=name, command=(sys.executable, "-m", "lookml_conformance.adapters", name))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)

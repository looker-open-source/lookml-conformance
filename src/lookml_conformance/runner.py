"""Run adapter commands against cases and collect the verdicts into a scorecard."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from lookml_conformance.cases import Case, FileOrder
from lookml_conformance.file_order import prepare
from lookml_conformance.judge import Verdict, judge_file_orders
from lookml_conformance.protocol import AdapterOutput, ProtocolError
from lookml_conformance.scorecard import AdapterRun, CaseResult, Scorecard

DEFAULT_TIMEOUT_SECONDS = 300.0
_TAIL = 500


class RegistryError(ValueError):
    """An adapter registry file that cannot be used."""


@dataclass(frozen=True)
class AdapterSpec:
    """How to run one adapter, plus the metadata shown in reports.

    ``command`` receives one or more project directories as its final arguments. Relative paths in
    it and in ``env`` are resolved against ``cwd``, which for a registry file is the file's
    directory. ``timeout`` applies per project. ``batch`` is false for adapters that must get one
    project per process. ``install`` maps a package manager (``pip`` or ``npm``) to the pinned
    package of the tool.
    """

    name: str
    command: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: Path | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    batch: bool = True
    label: str | None = None
    kind: str | None = None
    language: str | None = None
    url: str | None = None
    install: Mapping[str, str] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.label or self.name

    def invoke(self, project: Path) -> AdapterOutput:
        return self.invoke_many([project])[project.resolve()]

    def invoke_many(self, projects: Sequence[Path]) -> dict[Path, AdapterOutput]:
        """Resolve several projects in one process, keyed by resolved path.

        Projects the batch did not answer for (the tool crashed part-way, or the adapter only
        understands one project) are run again one at a time, so every project gets a result.
        """
        resolved = [project.resolve() for project in projects]
        outputs = self._run(resolved)
        if len(resolved) > 1:
            for project in resolved:
                if project not in outputs:
                    outputs |= self._run([project])
        return outputs

    def _run(self, projects: Sequence[Path]) -> dict[Path, AdapterOutput]:
        env = os.environ | {
            key: os.path.expandvars(os.path.expanduser(value)) for key, value in self.env.items()
        }
        command = [os.path.expanduser(part) for part in self.command] + [str(project) for project in projects]
        timeout = self.timeout * len(projects)
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, env=env, cwd=self.cwd, check=False
            )
        except subprocess.TimeoutExpired:
            if len(projects) > 1:
                return {}  # retried one project at a time
            return {projects[0]: AdapterOutput.failure(self.name, f"timed out after {timeout:g}s")}
        except OSError as exc:
            failure = AdapterOutput.failure(self.name, f"cannot run {command[0]!r}: {exc}")
            return dict.fromkeys(projects, failure)
        return parse_outputs(self.name, completed.stdout, completed.stderr, projects)


def parse_outputs(
    adapter: str, stdout: str, stderr: str, projects: Sequence[Path]
) -> dict[Path, AdapterOutput]:
    """Pair the JSON lines of a batch run with their projects through the ``project`` key.

    A run on a single project may omit ``project``; its last stdout line is then its result, as
    the protocol allows for adapters that only take one project.
    """
    by_name = {str(project): project for project in projects}
    outputs: dict[Path, AdapterOutput] = {}
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("project") not in by_name:
            continue
        project = by_name[data["project"]]
        try:
            outputs[project] = AdapterOutput.from_dict(data)
        except ProtocolError as exc:
            outputs[project] = AdapterOutput.failure(adapter, f"output does not follow the protocol: {exc}")
    if len(projects) == 1 and not outputs:
        outputs[projects[0]] = parse_output(adapter, stdout, stderr)
    return outputs


def parse_output(adapter: str, stdout: str, stderr: str = "") -> AdapterOutput:
    """Parse the last stdout line of an adapter run; anything unusable becomes a failure."""
    lines = stdout.strip().splitlines()
    if not lines:
        return AdapterOutput.failure(adapter, f"printed nothing on stdout; stderr: {stderr[-_TAIL:].strip()}")
    try:
        return AdapterOutput.from_dict(json.loads(lines[-1]))
    except json.JSONDecodeError:
        return AdapterOutput.failure(
            adapter, f"last stdout line is not JSON: {lines[-1][:200]!r}; stderr: {stderr[-_TAIL:].strip()}"
        )
    except ProtocolError as exc:
        return AdapterOutput.failure(adapter, f"output does not follow the protocol: {exc}")


def load_registry(path: Path) -> list[AdapterSpec]:
    """Read an adapter registry such as ``adapters.json``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["adapters"]
        return [
            AdapterSpec(
                name=entry["name"],
                command=tuple(entry["command"]),
                env=dict(entry.get("env", {})),
                cwd=path.parent.resolve(),
                timeout=float(entry.get("timeout", DEFAULT_TIMEOUT_SECONDS)),
                batch=bool(entry.get("batch", True)),
                label=entry.get("label"),
                kind=entry.get("kind"),
                language=entry.get("language"),
                url=entry.get("url"),
                install=dict(entry.get("install", {})),
            )
            for entry in entries
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RegistryError(f"{path}: {exc!r}") from exc


def select_adapters(adapters: Sequence[AdapterSpec], names: Iterable[str]) -> list[AdapterSpec]:
    """Keep the named adapters, in registry order. Raises :class:`RegistryError` for unknown names."""
    wanted = set(names)
    if unknown := sorted(wanted - {adapter.name for adapter in adapters}):
        known = ", ".join(adapter.name for adapter in adapters)
        raise RegistryError(f"unknown adapter(s) {', '.join(unknown)}; known: {known}")
    return [adapter for adapter in adapters if adapter.name in wanted]


ProgressCallback = Callable[[Case, AdapterSpec, Verdict], None]


def run_suite(
    cases: Sequence[Case],
    adapters: Sequence[AdapterSpec],
    *,
    jobs: int = 1,
    batch: bool = True,
    date: dt.date | None = None,
    progress: ProgressCallback | None = None,
) -> Scorecard:
    """Run every adapter on every case, ``jobs`` adapter processes at a time.

    With ``batch``, each adapter process resolves a chunk of cases, so a tool's start-up cost is
    paid once per chunk rather than once per case. ``jobs`` processes are shared between adapters.
    A case with ``order_variants`` is resolved in each layout of its project (see ``file_order``),
    written to a temporary directory, and passes only if it passes in all of them.
    """
    jobs = max(1, jobs)
    tasks = [
        (adapter, chunk)
        for adapter in adapters
        for chunk in _chunks(cases, max(1, jobs // len(adapters)) if batch and adapter.batch else len(cases))
    ]

    with tempfile.TemporaryDirectory(prefix="lookml-conformance-") as scratch:
        layouts: dict[str, list[tuple[FileOrder, Path]]] = {
            case.id: prepare(case, Path(scratch)) for case in cases
        }

        def run_task(task: tuple[AdapterSpec, list[Case]]) -> list[tuple[str, str, AdapterOutput, Verdict]]:
            adapter, chunk = task
            projects = [project for case in chunk for _, project in layouts[case.id]]
            if batch and adapter.batch:
                outputs = adapter.invoke_many(projects)
            else:
                outputs = {
                    key: value
                    for project in projects
                    for key, value in adapter.invoke_many([project]).items()
                }
            results = []
            for case in chunk:
                by_order = [(order, outputs[project.resolve()]) for order, project in layouts[case.id]]
                verdict = judge_file_orders(case, by_order)
                if progress is not None:
                    progress(case, adapter, verdict)
                results.append((case.id, adapter.name, by_order[0][1], verdict))
            return results

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            runs = {
                (case_id, name): (output, verdict)
                for results in pool.map(run_task, tasks)
                for case_id, name, output, verdict in results
            }

    versions: dict[str, str | None] = {adapter.name: None for adapter in adapters}
    for (_, name), (output, _) in runs.items():
        versions[name] = versions[name] or output.version
    return Scorecard(
        date=(date or dt.date.today()).isoformat(),
        adapters=tuple(AdapterRun(name=name, version=version) for name, version in versions.items()),
        results=tuple(
            CaseResult(
                case_id=case.id,
                category=case.category,
                status=case.status.value,
                verdicts={adapter.name: runs[case.id, adapter.name][1] for adapter in adapters},
            )
            for case in cases
        ),
    )


def _chunks(cases: Sequence[Case], count: int) -> list[list[Case]]:
    """Split ``cases`` into at most ``count`` contiguous chunks of nearly equal size."""
    count = max(1, min(count, len(cases)))
    size, extra = divmod(len(cases), count)
    chunks, start = [], 0
    for index in range(count):
        end = start + size + (index < extra)
        chunks.append(list(cases[start:end]))
        start = end
    return [chunk for chunk in chunks if chunk]

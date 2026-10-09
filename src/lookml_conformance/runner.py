"""Run adapter commands against cases and collect the verdicts into a scorecard."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from lookml_conformance.cases import Case
from lookml_conformance.judge import Verdict, judge
from lookml_conformance.protocol import AdapterOutput, ProtocolError
from lookml_conformance.scorecard import AdapterRun, CaseResult, Scorecard

DEFAULT_TIMEOUT_SECONDS = 300.0
_TAIL = 500


class RegistryError(ValueError):
    """An adapter registry file that cannot be used."""


@dataclass(frozen=True)
class AdapterSpec:
    """How to run one adapter, plus the metadata shown in reports.

    ``command`` receives the project directory as its final argument. Relative paths in it and in
    ``env`` are resolved against ``cwd``, which for a registry file is the file's directory.
    ``install`` maps a package manager (``pip`` or ``npm``) to the pinned package of the tool.
    """

    name: str
    command: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: Path | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    label: str | None = None
    kind: str | None = None
    language: str | None = None
    url: str | None = None
    install: Mapping[str, str] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.label or self.name

    def invoke(self, project: Path) -> AdapterOutput:
        env = os.environ | {
            key: os.path.expandvars(os.path.expanduser(value)) for key, value in self.env.items()
        }
        command = [os.path.expanduser(part) for part in self.command] + [str(project.resolve())]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=self.cwd,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return AdapterOutput.failure(self.name, f"timed out after {self.timeout:g}s")
        except OSError as exc:
            return AdapterOutput.failure(self.name, f"cannot run {command[0]!r}: {exc}")
        return parse_output(self.name, completed.stdout, completed.stderr)


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
    date: dt.date | None = None,
    progress: ProgressCallback | None = None,
) -> Scorecard:
    """Run every adapter on every case, ``jobs`` adapter processes at a time."""
    pairs = [(case, adapter) for case in cases for adapter in adapters]

    def run_pair(pair: tuple[Case, AdapterSpec]) -> tuple[AdapterOutput, Verdict]:
        case, adapter = pair
        output = adapter.invoke(case.project)
        verdict = judge(case, output)
        if progress is not None:
            progress(case, adapter, verdict)
        return output, verdict

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        runs = dict(
            zip(((case.id, adapter.name) for case, adapter in pairs), pool.map(run_pair, pairs), strict=True)
        )

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

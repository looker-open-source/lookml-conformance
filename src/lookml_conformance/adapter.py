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

"""The base class for Python adapters, and a launcher for adapters installed as entry points.

A Python adapter subclasses :class:`Adapter`, names the tool, and implements :meth:`Adapter.resolve`
for one project. The base class provides the command line, batches of projects, the tool version,
silencing of the tool's logging, and turning exceptions into ``error`` output::

    class MyToolAdapter(Adapter):
        name = "my-tool"
        distribution = "my-tool"   # the installed package, for the version

        def resolve(self, project: Path) -> dict[str, ModelOutput]:
            ...

    if __name__ == "__main__":
        raise SystemExit(MyToolAdapter.main())

A package can also expose its adapter under the ``lookml_conformance.adapters`` entry point group.
It then runs as ``python -m lookml_conformance.adapters <name> <project>...`` and
``lookml-conformance run --adapter <name>`` finds it without a registry entry.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import sys
import warnings
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import ClassVar

from lookml_conformance.protocol import AdapterOutput, Capabilities, ModelOutput

ENTRY_POINT_GROUP = "lookml_conformance.adapters"


class Adapter(ABC):
    """Runs one tool on LookML projects and reports what it resolved.

    Subclasses set ``name`` and ``distribution``, and ``capabilities`` when the tool lacks one, and
    implement :meth:`resolve`. An adapter reports what its tool produces and nothing more.
    """

    name: ClassVar[str]
    distribution: ClassVar[str]
    capabilities: ClassVar[Capabilities] = Capabilities()

    def __init__(self, options: argparse.Namespace | None = None) -> None:
        self.options = options or argparse.Namespace()
        self._diagnostics: list[str] = []

    @classmethod  # noqa: B027 - an optional hook, empty by default
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add tool-specific command-line options; they are available as ``self.options``."""

    @abstractmethod
    def resolve(self, project: Path) -> Mapping[str, ModelOutput]:
        """Resolve one project and return its models by name.

        A tool without model scoping returns one model under any name and sets
        ``capabilities = Capabilities(per_model=False)``.
        """

    def warn(self, message: str) -> None:
        """Record a diagnostic the tool reported while still producing a result."""
        self._diagnostics.append(message)

    def version(self) -> str | None:
        try:
            return importlib.metadata.version(self.distribution)
        except importlib.metadata.PackageNotFoundError:
            return None

    def run(self, project: str) -> AdapterOutput:
        """Resolve one project; any exception from the tool becomes an ``error`` output."""
        self._diagnostics = []
        try:
            models = self._quietly(Path(project).resolve())
        except Exception as exc:  # the tool's failure is the result being reported
            return AdapterOutput.failure(self.name, repr(exc), self.version(), project)
        return AdapterOutput(
            adapter=self.name,
            version=self.version(),
            project=project,
            capabilities=self.capabilities,
            models=dict(models),
            errors=tuple(self._diagnostics),
        )

    @classmethod
    def main(cls, argv: Sequence[str] | None = None) -> int:
        """Command-line entry point: print one JSON line per project given."""
        parser = argparse.ArgumentParser(description=f"lookml-conformance adapter for {cls.distribution}")
        parser.add_argument("projects", nargs="+", metavar="PROJECT", help="LookML project directories")
        cls.add_arguments(parser)
        options = parser.parse_args(argv)
        adapter = cls(options)
        for project in options.projects:
            sys.stdout.write(json.dumps(adapter.run(project).to_dict()) + "\n")
            sys.stdout.flush()  # the runner keeps finished projects if the tool crashes later
        return 0

    def _quietly(self, project: Path) -> Mapping[str, ModelOutput]:
        """Run the tool with its logging and warnings silenced, so stdout carries only results."""
        logging.disable(logging.CRITICAL)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return self.resolve(project)
        finally:
            logging.disable(logging.NOTSET)


class AdapterNotFound(LookupError):
    """No installed entry point provides the requested adapter."""


def installed_adapters() -> dict[str, importlib.metadata.EntryPoint]:
    """Adapters exposed by installed packages through the ``lookml_conformance.adapters`` group."""
    return {
        entry_point.name: entry_point
        for entry_point in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    }


def load_adapter(name: str) -> type[Adapter]:
    entry_point = installed_adapters().get(name)
    if entry_point is None:
        known = ", ".join(sorted(installed_adapters())) or "none"
        raise AdapterNotFound(f"no installed adapter named {name!r}; installed: {known}")
    try:
        adapter = entry_point.load()
    except ImportError as exc:
        raise AdapterNotFound(f"adapter {name!r} is installed but its tool is not: {exc}") from exc
    if not (isinstance(adapter, type) and issubclass(adapter, Adapter)):
        raise AdapterNotFound(f"entry point {name!r} ({entry_point.value}) is not an Adapter subclass")
    return adapter


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lookml_conformance.adapters <name> <project>...``: run an installed adapter."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0].startswith("-"):
        print("usage: python -m lookml_conformance.adapters NAME PROJECT [PROJECT ...]", file=sys.stderr)
        return 2
    try:
        adapter = load_adapter(args[0])
    except AdapterNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return adapter.main(args[1:])

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

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import warnings
from pathlib import Path

import pytest

from lookml_conformance import adapter as adapter_module
from lookml_conformance.adapter import Adapter, AdapterNotFound, installed_adapters, load_adapter, main
from lookml_conformance.protocol import AdapterOutput, Capabilities, ModelOutput, ViewOutput


class EchoAdapter(Adapter):
    """Reports one view whose table name is the project directory's name."""

    name = "echo"
    distribution = "pytest"
    capabilities = Capabilities(explores=False)

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--suffix", default="")

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        if project.name == "broken":
            raise KeyError("views")
        if project.name == "noisy":
            warnings.warn("noisy", UserWarning, stacklevel=1)
            logging.getLogger("tool").error("should be silenced")
            self.warn("partial result")
        table = project.name + getattr(self.options, "suffix", "")
        return {"m": ModelOutput(views={"orders": ViewOutput(sql_table_name=table)})}


def lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_run_reports_name_version_project_and_capabilities(tmp_path: Path) -> None:
    output = EchoAdapter().run(str(tmp_path / "shop"))

    assert output == AdapterOutput(
        adapter="echo",
        version=pytest.__version__,
        project=str(tmp_path / "shop"),
        capabilities=Capabilities(explores=False),
        models={"m": ModelOutput(views={"orders": ViewOutput(sql_table_name="shop")})},
    )


def test_run_turns_tool_exceptions_into_errors(tmp_path: Path) -> None:
    output = EchoAdapter().run(str(tmp_path / "broken"))

    assert output.error == "KeyError('views')"
    assert output.project == str(tmp_path / "broken")
    assert output.version == pytest.__version__


def test_run_collects_diagnostics_and_silences_the_tool(tmp_path: Path) -> None:
    adapter = EchoAdapter()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        noisy = adapter.run(str(tmp_path / "noisy"))
        quiet = adapter.run(str(tmp_path / "quiet"))

    assert caught == []
    assert noisy.errors == ("partial result",)
    assert quiet.errors == ()
    assert logging.getLogger("tool").isEnabledFor(logging.ERROR)


def test_version_is_none_for_an_unknown_distribution() -> None:
    class Unknown(EchoAdapter):
        distribution = "no-such-distribution-xyz"

    assert Unknown().version() is None


def test_main_prints_one_line_per_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    projects = [str(tmp_path / "a"), str(tmp_path / "broken"), str(tmp_path / "b")]

    assert EchoAdapter.main([*projects, "--suffix", "_x"]) == 0

    output = lines(capsys)
    assert [line["project"] for line in output] == projects
    assert output[0]["models"]["m"]["views"]["orders"]["sql_table_name"] == "a_x"  # type: ignore[index]
    assert output[1]["error"] == "KeyError('views')"


def test_an_adapter_must_implement_resolve() -> None:
    class Incomplete(Adapter):
        name = "incomplete"
        distribution = "x"

    with pytest.raises(TypeError, match="resolve"):
        Incomplete()  # type: ignore[abstract]


@pytest.fixture
def entry_points(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Pretend these entry points are installed in the lookml_conformance.adapters group."""
    values: dict[str, str] = {}

    def fake(group: str) -> list[importlib.metadata.EntryPoint]:
        assert group == adapter_module.ENTRY_POINT_GROUP
        return [importlib.metadata.EntryPoint(name, value, group) for name, value in values.items()]

    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    return values


def test_bundled_adapters_are_registered_as_entry_points() -> None:
    assert {"dagster", "datahub", "openmetadata"} <= set(installed_adapters())


def test_load_adapter(entry_points: dict[str, str]) -> None:
    entry_points["echo"] = f"{__name__}:EchoAdapter"
    entry_points["not-an-adapter"] = "json:dumps"
    entry_points["missing-tool"] = "no_such_module_xyz:Adapter"

    assert load_adapter("echo") is EchoAdapter
    with pytest.raises(AdapterNotFound, match="not an Adapter subclass"):
        load_adapter("not-an-adapter")
    with pytest.raises(AdapterNotFound, match="its tool is not"):
        load_adapter("missing-tool")
    with pytest.raises(AdapterNotFound, match="installed: echo, missing-tool, not-an-adapter"):
        load_adapter("other")


def test_launcher_runs_an_installed_adapter(
    entry_points: dict[str, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry_points["echo"] = f"{__name__}:EchoAdapter"

    assert main(["echo", str(tmp_path / "shop")]) == 0
    assert lines(capsys)[0]["adapter"] == "echo"


@pytest.mark.parametrize("argv", [[], ["--help"], ["unknown", "project"]])
def test_launcher_usage_errors(
    entry_points: dict[str, str], argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert capsys.readouterr().err

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lookml_conformance.protocol import AdapterOutput
from lookml_conformance.scaffold import adapter_template, class_name, module_name
from tests.conftest import CASES_ROOT


def test_names() -> None:
    assert module_name("my-tool") == "my_tool"
    assert class_name("my-tool") == "MyToolAdapter"
    assert class_name("looker2") == "Looker2Adapter"


@pytest.mark.parametrize("name", ["", "My-Tool", "my tool", "1tool", "my_tool"])
def test_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError, match="lowercase letters"):
        adapter_template(name)


def test_template_fills_in_the_names() -> None:
    source = adapter_template("my-tool", distribution="my-tool-core", path="adapters/my_tool.py")

    assert "class MyToolAdapter(Adapter):" in source
    assert 'name = "my-tool"' in source
    assert 'distribution = "my-tool-core"' in source
    assert "python adapters/my_tool.py <project>..." in source
    assert max(len(line) for line in source.splitlines()) <= 88


def test_generated_adapter_runs_and_follows_the_protocol(tmp_path: Path) -> None:
    script = tmp_path / "my_tool.py"
    script.write_text(adapter_template("my-tool"), encoding="utf-8")
    projects = [str(CASES_ROOT / "refinements" / "r04_later_include_wins" / "project"), str(tmp_path)]

    completed = subprocess.run(
        [sys.executable, str(script), *projects], capture_output=True, text=True, check=True
    )

    outputs = [AdapterOutput.from_dict(json.loads(line)) for line in completed.stdout.splitlines()]
    assert [output.project for output in outputs] == projects
    assert [output.adapter for output in outputs] == ["my-tool", "my-tool"]
    assert list(outputs[0].models) == ["m"]
    assert outputs[1].models == {}

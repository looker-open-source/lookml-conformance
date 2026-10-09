from __future__ import annotations

from pathlib import Path

import pytest

from lookml_conformance.environments import SetupError, environment_path, setup, setup_commands
from lookml_conformance.runner import AdapterSpec

PIP = AdapterSpec("tool", ("x",), install={"pip": "tool==1.0"})
NPM = AdapterSpec("parser", ("x",), install={"npm": "parser@2.0"})
PACKAGES = ["tool==1.0", "--editable", "/repo"]


def test_environment_path() -> None:
    assert environment_path(Path("/repo"), PIP) == Path("/repo/.envs/tool")


def test_pip_tool_with_uv() -> None:
    commands = setup_commands(PIP, Path("/repo"), "python3.11", "uv")

    assert commands == [
        ["uv", "venv", "--quiet", "--allow-existing", "--python", "python3.11", "/repo/.envs/tool"],
        ["uv", "pip", "install", "--quiet", "--python", "/repo/.envs/tool/bin/python", *PACKAGES],
    ]


def test_pip_tool_without_uv() -> None:
    commands = setup_commands(PIP, Path("/repo"), "python3", None)

    assert commands == [
        ["python3", "-m", "venv", "/repo/.envs/tool"],
        ["/repo/.envs/tool/bin/python", "-m", "pip", "install", "--quiet", *PACKAGES],
    ]


def test_npm_tool() -> None:
    assert setup_commands(NPM, Path("/repo"), "python3", "uv") == [
        ["npm", "install", "--silent", "--no-save", "--prefix", "/repo/.envs/parser", "parser@2.0"]
    ]


def test_adapter_without_install_entry() -> None:
    with pytest.raises(SetupError, match="no 'install' entry"):
        setup_commands(AdapterSpec("bare", ("x",)), Path("/repo"), "python3", None)


def test_setup_runs_every_command_in_order() -> None:
    ran: list[list[str]] = []

    setup([PIP, NPM], Path("/repo"), python="python3", run=ran.append, uv="uv")

    assert [command[:2] for command in ran] == [["uv", "venv"], ["uv", "pip"], ["npm", "install"]]

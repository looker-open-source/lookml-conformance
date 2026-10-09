"""Create the environments that hold the tool versions named in the adapter registry.

Each adapter gets ``.envs/<adapter name>/``: a virtual environment with the tool and this package for
``pip`` tools, or an npm prefix for ``npm`` tools. The registry commands point into these
directories, so ``lookml-conformance run`` reproduces the published scorecard.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from lookml_conformance.runner import AdapterSpec

ENVS_DIR = ".envs"

Command = list[str]
Runner = Callable[[Command], object]


class SetupError(ValueError):
    """An adapter whose environment cannot be created."""


def environment_path(root: Path, adapter: AdapterSpec) -> Path:
    return root / ENVS_DIR / adapter.name


def setup_commands(adapter: AdapterSpec, root: Path, python: str, uv: str | None) -> list[Command]:
    """The commands that create ``adapter``'s environment under ``root``."""
    env = environment_path(root, adapter)
    if "pip" in adapter.install:
        packages = [adapter.install["pip"], "--editable", str(root)]
        env_python = str(env / "bin" / "python")
        if uv:
            return [
                [uv, "venv", "--quiet", "--allow-existing", "--python", python, str(env)],
                [uv, "pip", "install", "--quiet", "--python", env_python, *packages],
            ]
        return [[python, "-m", "venv", str(env)], [env_python, "-m", "pip", "install", "--quiet", *packages]]
    if "npm" in adapter.install:
        return [["npm", "install", "--silent", "--no-save", "--prefix", str(env), adapter.install["npm"]]]
    raise SetupError(f"adapter {adapter.name!r} has no 'install' entry with 'pip' or 'npm'")


def setup(
    adapters: Sequence[AdapterSpec],
    root: Path,
    python: str = "python3",
    run: Runner | None = None,
    uv: str | None = None,
) -> None:
    """Create every adapter's environment. Uses ``uv`` when it is on PATH, otherwise venv and pip."""
    uv = uv if uv is not None else shutil.which("uv")
    run = run or (lambda command: subprocess.run(command, check=True))
    for adapter in adapters:
        for command in setup_commands(adapter, root, python, uv):
            run(command)

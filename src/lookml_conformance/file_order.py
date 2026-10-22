"""Write the layouts of a case's project that differ in the order a file listing returns its files.

Some tools read a project's files in the order the file system lists them instead of following
include statements. On such a tool, a case whose answer depends on the order of two files passes
or fails by the luck of that listing. A case lists those pairs of files in ``order_variants``, and
the runner resolves the project in each layout:

- as written, and
- for each pair, with the contents of the two files exchanged. Include statements that name either
  file are rewritten to name the other, so every include still reaches the same declarations and
  the include order does not change.

Every layout is written into a fresh directory, file by file in path order. The two layouts have
the same paths, written in the same order, so a file system that lists a directory by the names of
its files (APFS, ext4) or by the order they were created (tmpfs, Btrfs) lists them in the same
order in both. A tool that reads the files in that order therefore reads the two exchanged
contents in one order in one layout and in the opposite order in the other, while a tool that
follows include order sees no difference.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from lookml_conformance.cases import IMPORTED_PROJECTS_DIR, Case, FileOrder

LKML_SUFFIX = ".lkml"
_INCLUDE = re.compile(r'^(?P<head>[ \t]*include[ \t]*:[ \t]*")(?P<path>[^"\n]*)(?P<tail>")', re.MULTILINE)
_WILDCARD = re.compile(r"[*?\[]")


def layout(project: Path, order: FileOrder) -> dict[str, bytes]:
    """The files of ``project`` in the given layout, keyed by path relative to the project."""
    files = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }
    if order.exchange is None:
        return files
    first, second = order.exchange
    renamed = {first: second, second: first}
    exchanged = {renamed.get(path, path): content for path, content in files.items()}
    return {
        path: rewrite_includes(content.decode("utf-8"), path, renamed).encode("utf-8")
        if path.endswith(LKML_SUFFIX) and not _in_imported_project(path)
        else content
        for path, content in exchanged.items()
    }


def rewrite_includes(text: str, path: str, renamed: Mapping[str, str]) -> str:
    """Rewrite include statements of the file at ``path`` that name a file in ``renamed``.

    ``renamed`` maps a path relative to the project to the path its content moved to. Includes with
    a wildcard match the same paths in every layout and are kept, as are includes of imported
    projects (``//``). An include written without the ``.lkml`` extension stays without it.
    """

    def replace(match: re.Match[str]) -> str:
        include = match["path"]
        if include.startswith("//") or _WILDCARD.search(include):
            return match[0]
        if include.startswith("/"):
            target = include.lstrip("/")
        else:
            target = posixpath.join(posixpath.dirname(path), include)
        target = posixpath.normpath(target)
        if target in renamed:
            new_name = posixpath.basename(renamed[target])
        elif target + LKML_SUFFIX in renamed:
            new_name = posixpath.basename(renamed[target + LKML_SUFFIX]).removesuffix(LKML_SUFFIX)
        else:
            return match[0]
        return match["head"] + posixpath.join(posixpath.dirname(include), new_name) + match["tail"]

    return _INCLUDE.sub(replace, text)


def write_layout(files: Mapping[str, bytes], destination: Path) -> Path:
    """Write ``files`` under ``destination``, one by one in path order, and return ``destination``."""
    for path in sorted(files):
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[path])
    return destination


def prepare(case: Case, root: Path) -> list[tuple[FileOrder, Path]]:
    """The project directory to resolve for each layout of ``case``.

    A case without ``order_variants`` runs on its own ``project/``. Otherwise every layout,
    including the one as written, is written under ``root``: ``<root>/<case id>/project`` as
    written and ``<root>/<case id>.exchange-<n>/project`` for the n-th variant.
    """
    if not case.order_variants:
        return [(case.file_orders[0], case.project)]
    prepared = []
    for index, order in enumerate(case.file_orders):
        name = case.id if order.exchange is None else f"{case.id}.exchange-{index}"
        destination = write_layout(layout(case.project, order), root / name / "project")
        prepared.append((order, destination))
    return prepared


def _in_imported_project(path: str) -> bool:
    return PurePosixPath(path).parts[0] == IMPORTED_PROJECTS_DIR

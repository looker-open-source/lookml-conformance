"""Load and validate conformance cases.

A case is a directory ``cases/<category>/<case id>/`` with two entries:

``case.json``
    What the case tests, the documentation it cites, and the expected resolution.
``project/``
    A minimal LookML project. Imported projects live under ``project/imported_projects/<name>/``.

The format is described in ``docs/case-format.md``.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

CASE_FILE = "case.json"
PROJECT_DIR = "project"
IMPORTED_PROJECTS_DIR = "imported_projects"
MODEL_SUFFIX = ".model.lkml"

CATEGORIES = (
    "refinements",
    "includes",
    "extends",
    "model_scope",
    "explores",
    "constants",
    "lineage",
    "syntax",
)
CAPABILITIES = ("explores", "imported_projects", "constants", "lineage")

VIEW_KEYS = frozenset(
    {"sql_table_name", "derived_table", "fields", "field_params", "extends", "upstream_tables"}
)
EXPLORE_KEYS = frozenset({"view_name", "from", "label", "joins"})
JOIN_KEYS = frozenset({"from", "view_label", "sql_on", "relationship", "type"})
FIELD_LIST_PARAMS = frozenset({"timeframes"})

_TOP_KEYS = frozenset(
    {
        "id",
        "title",
        "rule",
        "status",
        "basis",
        "citations",
        "rationale",
        "provisional",
        "observations",
        "invalid_in_looker",
        "expect",
    }
)
_CASE_ID = re.compile(r"^[a-z]\d{2}_[a-z0-9_]+$")
_CONSTANT_DECLARATION = re.compile(r"^\s*constant\s*:", re.MULTILINE)
_OBSERVATION_KEYS = frozenset({"looker_version", "date", "finding", "evidence"})


class Status(str, Enum):
    """Whether an expectation can be relied on.

    ``confirmed`` expectations rest on a :class:`Basis`. ``provisional`` ones cover behavior that is
    neither documented nor observed yet; they name the public source they are pinned to.
    """

    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"


class Basis(str, Enum):
    """What a confirmed expectation rests on.

    ``documentation``: the cited Looker documentation settles the rule. ``observation``: Looker was
    seen to behave this way; the case lists the observations with their evidence.
    """

    DOCUMENTATION = "documentation"
    OBSERVATION = "observation"


class CaseError(ValueError):
    """A case directory that does not follow the case format."""

    def __init__(self, path: Path, problems: Iterable[str]) -> None:
        self.path = path
        self.problems = tuple(problems)
        super().__init__(f"{path}: " + "; ".join(self.problems))


class SuiteError(ValueError):
    """One or more invalid cases in a suite."""

    def __init__(self, errors: Iterable[CaseError]) -> None:
        self.errors = tuple(errors)
        super().__init__("\n".join(str(error) for error in self.errors))


@dataclass(frozen=True)
class Citation:
    """A documentation page and a verbatim quote from it."""

    url: str
    quote: str


@dataclass(frozen=True)
class Provenance:
    """Where a provisional expectation comes from while the documentation is silent."""

    question: str
    pinned_to: str


@dataclass(frozen=True)
class Observation:
    """What a Looker instance did with the case's project, and where the evidence is kept.

    ``evidence`` is a path relative to the repository root.
    """

    looker_version: str
    date: datetime.date
    finding: str
    evidence: str


@dataclass(frozen=True)
class ModelExpectation:
    """Assertions about one model. Only the keys present in each entry are checked."""

    views: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    explores: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    title: str
    rule: str
    status: Status
    citations: tuple[Citation, ...]
    models: Mapping[str, ModelExpectation]
    directory: Path
    absent_views: tuple[str, ...] = ()
    invalid_in_looker: bool = False
    rationale: str | None = None
    provisional: Provenance | None = None
    basis: tuple[Basis, ...] = ()
    observations: tuple[Observation, ...] = ()

    @property
    def project(self) -> Path:
        return self.directory / PROJECT_DIR

    @property
    def requires(self) -> frozenset[str]:
        """Adapter capabilities this case needs, derived from its expectations and project."""
        needed = set()
        if any(model.explores for model in self.models.values()):
            needed.add("explores")
        if any("upstream_tables" in view for model in self.models.values() for view in model.views.values()):
            needed.add("lineage")
        if (self.project / IMPORTED_PROJECTS_DIR).is_dir():
            needed.add("imported_projects")
        manifest = self.project / "manifest.lkml"
        if manifest.is_file() and _CONSTANT_DECLARATION.search(manifest.read_text(encoding="utf-8")):
            needed.add("constants")
        return frozenset(needed)

    def project_files(self) -> list[Path]:
        """Every file of the LookML project, relative to the project directory, in path order."""
        return sorted(path.relative_to(self.project) for path in self.project.rglob("*") if path.is_file())


def load_case(directory: Path) -> Case:
    """Load ``directory/case.json`` and check it against the case format."""
    path = directory / CASE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseError(path, [str(exc)]) from exc
    if not isinstance(data, dict):
        raise CaseError(path, ["the top level must be a JSON object"])

    check = _Checker()
    check.no_unknown_keys(data, _TOP_KEYS, "case")
    case_id = check.string(data, "id")
    if case_id is not None:
        if case_id != directory.name:
            check.problem(f"id {case_id!r} does not match the directory name {directory.name!r}")
        if not _CASE_ID.match(case_id):
            check.problem(f"id {case_id!r} must look like 'r01_snake_case'")
    category = directory.parent.name
    if category not in CATEGORIES:
        check.problem(f"category directory {category!r} is not one of {', '.join(CATEGORIES)}")

    status = check.enum(data, "status", Status)
    citations = check.citations(data)
    provisional = check.provenance(data, status)
    basis = check.basis(data, status)
    observations = check.observations(data, status, basis, directory.parent.parent.parent)
    models, absent_views = check.expectations(data.get("expect"))
    check.project(directory / PROJECT_DIR, models)

    case = Case(
        id=case_id or directory.name,
        category=category,
        title=check.string(data, "title") or "",
        rule=check.string(data, "rule") or "",
        status=status or Status.PROVISIONAL,
        citations=citations,
        models=models,
        directory=directory,
        absent_views=absent_views,
        invalid_in_looker=check.boolean(data, "invalid_in_looker", default=False),
        rationale=check.string(data, "rationale", required=False),
        provisional=provisional,
        basis=basis,
        observations=observations,
    )
    if check.problems:
        raise CaseError(path, check.problems)
    return case


def case_directories(root: Path) -> list[Path]:
    """Directories under ``root`` that contain a ``case.json``, in suite order."""
    return sorted((path.parent for path in root.glob(f"*/*/{CASE_FILE}")), key=_suite_order)


def load_cases(root: Path, only: str | None = None) -> list[Case]:
    """Load every case under ``root``, optionally only those whose id contains ``only``.

    Raises :class:`SuiteError` listing every invalid case, so one run reports all problems.
    """
    cases: list[Case] = []
    errors: list[CaseError] = []
    for directory in case_directories(root):
        if only is not None and only not in directory.name:
            continue
        try:
            cases.append(load_case(directory))
        except CaseError as error:
            errors.append(error)
    if errors:
        raise SuiteError(errors)
    ids = [case.id for case in cases]
    if duplicates := sorted({case_id for case_id in ids if ids.count(case_id) > 1}):
        raise SuiteError([CaseError(root, [f"duplicate case ids: {', '.join(duplicates)}"])])
    return cases


def _suite_order(directory: Path) -> tuple[int, str]:
    category = directory.parent.name
    rank = CATEGORIES.index(category) if category in CATEGORIES else len(CATEGORIES)
    return rank, directory.name


class _Checker:
    """Collects every problem in a case file instead of stopping at the first one."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def problem(self, message: str) -> None:
        self.problems.append(message)

    def no_unknown_keys(self, data: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
        if unknown := sorted(set(data) - allowed):
            self.problem(f"{where}: unknown keys {unknown}; allowed: {sorted(allowed)}")

    def string(self, data: Mapping[str, Any], key: str, required: bool = True) -> str | None:
        value = data.get(key)
        if value is None:
            if required:
                self.problem(f"{key!r} is required")
            return None
        if not isinstance(value, str) or not value.strip():
            self.problem(f"{key!r} must be a non-empty string")
            return None
        return value

    def boolean(self, data: Mapping[str, Any], key: str, default: bool) -> bool:
        value = data.get(key, default)
        if not isinstance(value, bool):
            self.problem(f"{key!r} must be true or false")
            return default
        return value

    def enum(self, data: Mapping[str, Any], key: str, kind: type[Status]) -> Status | None:
        value = self.string(data, key)
        if value is None:
            return None
        try:
            return kind(value)
        except ValueError:
            self.problem(f"{key!r} must be one of {[member.value for member in kind]}")
            return None

    def citations(self, data: Mapping[str, Any]) -> tuple[Citation, ...]:
        raw = data.get("citations")
        if not isinstance(raw, list) or not raw:
            self.problem("'citations' must be a non-empty list")
            return ()
        citations = []
        for index, entry in enumerate(raw):
            where = f"citations[{index}]"
            if not isinstance(entry, dict):
                self.problem(f"{where} must be an object with 'url' and 'quote'")
                continue
            self.no_unknown_keys(entry, frozenset({"url", "quote"}), where)
            url, quote = entry.get("url"), entry.get("quote")
            if not isinstance(url, str) or not url.startswith("https://"):
                self.problem(f"{where}.url must be an https URL")
                continue
            if not isinstance(quote, str) or not quote.strip():
                self.problem(f"{where}.quote must be a non-empty verbatim quote")
                continue
            citations.append(Citation(url=url, quote=quote))
        return tuple(citations)

    def provenance(self, data: Mapping[str, Any], status: Status | None) -> Provenance | None:
        raw = data.get("provisional")
        if status is Status.CONFIRMED:
            if raw is not None:
                self.problem("confirmed cases must not have a 'provisional' block")
            return None
        if status is not Status.PROVISIONAL:
            return None
        if not isinstance(raw, dict):
            self.problem("provisional cases need a 'provisional' block with 'question' and 'pinned_to'")
            return None
        self.no_unknown_keys(raw, frozenset({"question", "pinned_to"}), "provisional")
        question = self.string(raw, "question")
        pinned_to = self.string(raw, "pinned_to")
        if question is None or pinned_to is None:
            return None
        return Provenance(question=question, pinned_to=pinned_to)

    def basis(self, data: Mapping[str, Any], status: Status | None) -> tuple[Basis, ...]:
        raw = data.get("basis")
        if status is Status.PROVISIONAL:
            if raw is not None:
                self.problem("provisional cases must not have a 'basis'")
            return ()
        if status is not Status.CONFIRMED:
            return ()
        allowed = [member.value for member in Basis]
        if not _is_list_of(raw, str) or not raw or any(item not in allowed for item in raw):
            self.problem(f"confirmed cases need a 'basis': a non-empty list of {allowed}")
            return ()
        if len(set(raw)) != len(raw):
            self.problem("'basis' must not repeat an entry")
        return tuple(Basis(item) for item in dict.fromkeys(raw))

    def observations(
        self, data: Mapping[str, Any], status: Status | None, basis: tuple[Basis, ...], repo_root: Path
    ) -> tuple[Observation, ...]:
        raw = data.get("observations")
        if raw is None:
            if Basis.OBSERVATION in basis:
                self.problem("a case with basis 'observation' needs 'observations'")
            return ()
        if status is Status.PROVISIONAL:
            self.problem("provisional cases must not have 'observations'; an observed case is confirmed")
            return ()
        if Basis.OBSERVATION not in basis:
            self.problem("a case with 'observations' must list 'observation' in its 'basis'")
        if not isinstance(raw, list) or not raw:
            self.problem("'observations' must be a non-empty list")
            return ()
        observations = []
        for index, entry in enumerate(raw):
            where = f"observations[{index}]"
            if not isinstance(entry, dict):
                self.problem(f"{where} must be an object with {sorted(_OBSERVATION_KEYS)}")
                continue
            self.no_unknown_keys(entry, _OBSERVATION_KEYS, where)
            if missing := sorted(key for key in _OBSERVATION_KEYS if not _is_text(entry.get(key))):
                self.problem(f"{where}: {missing} must be non-empty strings")
                continue
            values: dict[str, str] = {key: entry[key] for key in _OBSERVATION_KEYS}
            try:
                date = datetime.date.fromisoformat(values["date"])
            except ValueError:
                self.problem(f"{where}.date must be a date like 2026-10-14")
                continue
            evidence = Path(values["evidence"])
            if evidence.is_absolute() or ".." in evidence.parts:
                self.problem(f"{where}.evidence must be a path relative to the repository root")
                continue
            if not (repo_root / evidence).exists():
                self.problem(f"{where}.evidence {values['evidence']!r} does not exist")
                continue
            observations.append(
                Observation(
                    looker_version=values["looker_version"],
                    date=date,
                    finding=values["finding"],
                    evidence=evidence.as_posix(),
                )
            )
        return tuple(observations)

    def expectations(self, raw: Any) -> tuple[dict[str, ModelExpectation], tuple[str, ...]]:
        if not isinstance(raw, dict):
            self.problem("'expect' must be an object with 'models'")
            return {}, ()
        self.no_unknown_keys(raw, frozenset({"models", "absent_views"}), "expect")
        raw_models = raw.get("models")
        if not isinstance(raw_models, dict) or not raw_models:
            self.problem("'expect.models' must map at least one model name to its expectations")
            raw_models = {}
        models = {name: self.model(name, spec) for name, spec in raw_models.items()}
        absent = raw.get("absent_views", [])
        if not _is_list_of(absent, str):
            self.problem("'expect.absent_views' must be a list of view names")
            absent = []
        return models, tuple(absent)

    def model(self, name: str, raw: Any) -> ModelExpectation:
        where = f"expect.models.{name}"
        if not isinstance(raw, dict):
            self.problem(f"{where} must be an object")
            return ModelExpectation()
        self.no_unknown_keys(raw, frozenset({"views", "explores"}), where)
        views = raw.get("views", {})
        explores = raw.get("explores", {})
        if not views and not explores:
            self.problem(f"{where} must assert at least one view or explore")
        for view_name, view in _as_dict(views).items():
            self.view(f"{where}.views.{view_name}", view)
        for explore_name, explore in _as_dict(explores).items():
            self.explore(f"{where}.explores.{explore_name}", explore)
        return ModelExpectation(views=_as_dict(views), explores=_as_dict(explores))

    def view(self, where: str, raw: Any) -> None:
        if not isinstance(raw, dict) or not raw:
            self.problem(f"{where} must be a non-empty object")
            return
        self.no_unknown_keys(raw, VIEW_KEYS, where)
        if "sql_table_name" in raw and not isinstance(raw["sql_table_name"], (str, type(None))):
            self.problem(f"{where}.sql_table_name must be a string or null")
        if (
            "derived_table" in raw
            and raw["derived_table"] is not None
            and not _is_str_map(raw["derived_table"])
        ):
            self.problem(f"{where}.derived_table must map parameter names to strings, or be null")
        for key in ("fields", "extends", "upstream_tables"):
            if key in raw and not _is_list_of(raw[key], str):
                self.problem(f"{where}.{key} must be a list of strings")
        for field_name, params in _as_dict(raw.get("field_params", {})).items():
            self.field_params(f"{where}.field_params.{field_name}", params)

    def field_params(self, where: str, raw: Any) -> None:
        if not isinstance(raw, dict) or not raw:
            self.problem(f"{where} must be a non-empty object")
            return
        for param, value in raw.items():
            if param == "filters":
                if not (
                    _is_list_of(value, dict)
                    and all(_is_str_map(entry) and len(entry) == 1 for entry in value)
                ):
                    self.problem(
                        f"{where}.filters must be a list of one-key objects, e.g. [{{'status': 'x'}}]"
                    )
            elif param in FIELD_LIST_PARAMS:
                if not _is_list_of(value, str):
                    self.problem(f"{where}.{param} must be a list of strings")
            elif not isinstance(value, str):
                self.problem(f"{where}.{param} must be a string")

    def explore(self, where: str, raw: Any) -> None:
        if not isinstance(raw, dict) or not raw:
            self.problem(f"{where} must be a non-empty object")
            return
        self.no_unknown_keys(raw, EXPLORE_KEYS, where)
        for key in ("view_name", "from", "label"):
            if key in raw and not isinstance(raw[key], (str, type(None))):
                self.problem(f"{where}.{key} must be a string or null")
        for join_name, join in _as_dict(raw.get("joins", {})).items():
            if not isinstance(join, dict):
                self.problem(f"{where}.joins.{join_name} must be an object")
                continue
            self.no_unknown_keys(join, JOIN_KEYS, f"{where}.joins.{join_name}")

    def project(self, project: Path, models: Mapping[str, ModelExpectation]) -> None:
        if not project.is_dir():
            self.problem(f"missing LookML project directory {project.name}/")
            return
        model_files = {
            path.name.removesuffix(MODEL_SUFFIX)
            for path in project.rglob(f"*{MODEL_SUFFIX}")
            if IMPORTED_PROJECTS_DIR not in path.relative_to(project).parts
        }
        if missing := sorted(set(models) - model_files):
            self.problem(f"expected models without a .model.lkml file in project/: {missing}")


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_list_of(value: Any, kind: type) -> bool:
    return isinstance(value, list) and all(isinstance(item, kind) for item in value)


def _is_str_map(value: Any) -> bool:
    return isinstance(value, dict) and all(isinstance(item, str) for item in value.values())

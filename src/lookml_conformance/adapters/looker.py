"""Adapter for Looker itself: resolves each case on a Looker instance through the Looker API.

The other adapters run a tool that reads LookML from git. This one asks Looker, so its scorecard
shows what Looker does with each case. It is how provisional cases are checked.

For each project the adapter:

1. commits the project to one branch of a git repository the Looker project is connected to, and
   pushes it (``--repo``, ``--branch``);
2. checks that branch out in the Looker project's development workspace, resets it to the remote,
   and checks that Looker reports the pushed commit;
3. configures any model the project declares that Looker does not know yet;
4. runs the LookML validator and reports its messages as diagnostics;
5. reads every explore of every model, and asks Looker for the SQL of a one-field query per view.

What is reported comes from Looker as follows:

- explores, joins and fields come from the explore metadata (``lookml_model_explore``);
- ``sql_table_name``, ``derived_table.sql`` and lineage come from the SQL Looker generates
  (``run_inline_query`` with result format ``sql``; nothing runs on the database);
- ``extends`` is not exposed by the API and is reported as unknown (``null``).

Looker exposes a view only through an explore. When a model file names a view in no explore, join,
``view_name`` or ``from``, the adapter appends ``explore: lc_probe__<view> { from: <view> }`` to the
pushed copy of the model, so the view can be observed. Probe explores are not reported as explores,
and validator messages about them are dropped. Connection names in model files are replaced with
``--connection``. Nothing else in the project is changed.

Imported projects are not supported yet (they need a second Looker project), so those cases are
scored N/A.

Configuration comes from options or environment variables:

=====================  =========================  ============================================
Option                 Environment variable       Meaning
=====================  =========================  ============================================
``--base-url``         ``LOOKERSDK_BASE_URL``     Instance URL, for example https://x.looker.app
``--client-id``        ``LOOKERSDK_CLIENT_ID``    API key client ID
``--client-secret``    ``LOOKERSDK_CLIENT_SECRET`` API key client secret
``--looker-project``   ``LOOKER_PROJECT``         Looker project ID
``--repo``             ``LOOKER_REPO``            Local clone of the project's git remote
``--connection``       ``LOOKER_CONNECTION``      Connection name written into model files
``--branch``           ``LOOKER_BRANCH``          Branch to use (default ``lookml-conformance``)
``--dump``             ``LOOKER_DUMP``            Directory for the raw API responses per case
=====================  =========================  ============================================

Run it with one process at a time (``lookml-conformance run --jobs 1``). A lock file in the
repository also serializes concurrent processes.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.cases import IMPORTED_PROJECTS_DIR, MODEL_SUFFIX
from lookml_conformance.normalize import collapse_whitespace
from lookml_conformance.protocol import (
    Capabilities,
    ExploreOutput,
    ModelOutput,
    Upstream,
    ViewOutput,
)

PROBE_PREFIX = "lc_probe__"
DEFAULT_BRANCH = "lookml-conformance"
LOCK_FILE = "lookml-conformance-looker.lock"


# --------------------------------------------------------------------------------------------------
# Looker API
# --------------------------------------------------------------------------------------------------


class LookerApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"{method} {path}: HTTP {status}: {body[:500]}")
        self.status = status


class LookerApi:
    """A minimal Looker API 4.0 client on the standard library."""

    def __init__(self, base_url: str, client_id: str, client_secret: str, timeout: float = 120) -> None:
        self.root = base_url.rstrip("/") + "/api/4.0"
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self._token: str | None = None

    def login(self) -> None:
        form = urllib.parse.urlencode({"client_id": self._client_id, "client_secret": self._client_secret})
        body = self._send("POST", "/login", form.encode(), "application/x-www-form-urlencoded", auth=False)
        self._token = json.loads(body)["access_token"]

    def get(self, path: str, query: Mapping[str, str] | None = None) -> Any:
        return self.call("GET", path, query=query)

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        query: Mapping[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        if self._token is None:
            self.login()
        if query:
            path = f"{path}?{urllib.parse.urlencode(query)}"
        data = None if body is None else json.dumps(body).encode()
        try:
            text = self._send(method, path, data, "application/json")
        except LookerApiError as exc:
            if exc.status != 401:
                raise
            self.login()  # the token expired
            text = self._send(method, path, data, "application/json")
        if raw:
            return text
        return json.loads(text) if text.strip() else None

    def _send(self, method: str, path: str, data: bytes | None, content_type: str, auth: bool = True) -> str:
        headers = {"Content-Type": content_type, "Accept": "application/json"}
        if auth and self._token:
            headers["Authorization"] = f"token {self._token}"
        request = urllib.request.Request(self.root + path, data=data, method=method, headers=headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    return str(response.read().decode())
            except urllib.error.HTTPError as exc:
                body = exc.read().decode(errors="replace")
                if exc.code >= 500 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise LookerApiError(method, path.split("?")[0], exc.code, body) from None
        raise AssertionError("unreachable")


# --------------------------------------------------------------------------------------------------
# Staging a project on the Looker project's git remote
# --------------------------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


@contextlib.contextmanager
def repo_lock(repo: Path) -> Iterator[None]:
    """Serialize adapter processes that share a repository (and so a Looker branch)."""
    with open(repo / ".git" / LOCK_FILE, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def set_connection(text: str, connection: str) -> str:
    return re.sub(r'^(\s*connection:\s*)"[^"]*"', lambda m: f'{m.group(1)}"{connection}"', text, flags=re.M)


_VIEW_DEFINITION = re.compile(r"^\s*view:\s*(\w+)\s*\{", re.M)
_BOUND_VIEW = re.compile(r"\b(?:explore|view_name|from|join):\s*\+?(\w+)")


def defined_views(root: Path) -> list[str]:
    """Names of views the project defines (``view: name {``, not refinements), in file order."""
    names: list[str] = []
    for path in sorted(root.rglob("*.lkml")):
        if IMPORTED_PROJECTS_DIR in path.relative_to(root).parts or path.name.endswith(MODEL_SUFFIX):
            continue
        names += [name for name in _VIEW_DEFINITION.findall(path.read_text()) if name not in names]
    return names


def probe_explores(model_text: str, views: Sequence[str]) -> str:
    """Explores to append to a model so that Looker exposes the views the model names nowhere."""
    bound = set(_BOUND_VIEW.findall(model_text))
    return "".join(
        f"\nexplore: {PROBE_PREFIX}{view} {{ from: {view} }}\n" for view in views if view not in bound
    )


def stage_project(project: Path, repo: Path, branch: str, connection: str | None, message: str) -> str:
    """Replace the branch's files with ``project``, commit, force-push, and return the commit."""
    git(repo, "checkout", "-q", "-B", branch)
    for entry in repo.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    shutil.copytree(project, repo, dirs_exist_ok=True)
    views = defined_views(repo)
    for model in kit.model_files(repo):
        text = model.read_text()
        if connection:
            text = set_connection(text, connection)
        model.write_text(text + probe_explores(text, views))
    # Clearing the index first makes git record renames that only change case on macOS.
    git(repo, "rm", "-r", "-q", "--cached", "--ignore-unmatch", ".")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "push", "-q", "-f", "origin", f"HEAD:refs/heads/{branch}")
    return sha


# --------------------------------------------------------------------------------------------------
# Reading Looker's generated SQL
# --------------------------------------------------------------------------------------------------

_QUOTES = "'\"`"
_IDENTIFIER_QUOTES = '"`'
_NOT_ALIAS = {
    "on", "using", "where", "group", "order", "limit", "left", "right", "inner", "outer", "full",
    "cross", "join", "union", "having", "qualify", "window", "lateral", "natural", "select",
}  # fmt: skip


@dataclass(frozen=True)
class Source:
    """One item after FROM or JOIN: a table, or a parenthesized query. ``alias`` is lower-cased."""

    table: str | None
    query: str | None
    alias: str


def _skip_quoted(sql: str, start: int) -> int:
    """Index after the quoted literal or identifier that starts at ``start``."""
    quote, i = sql[start], start + 1
    while i < len(sql):
        if sql[i] == "\\":
            i += 2
            continue
        if sql[i] == quote:
            if i + 1 < len(sql) and sql[i + 1] == quote:
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _skip_parens(sql: str, start: int) -> int:
    """Index after the parenthesis that closes the one at ``start``."""
    depth, i = 0, start
    while i < len(sql):
        char = sql[i]
        if char in _QUOTES:
            i = _skip_quoted(sql, i)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def strip_comments(sql: str) -> str:
    out, i = [], 0
    while i < len(sql):
        if sql[i] in _QUOTES:
            end = _skip_quoted(sql, i)
            out.append(sql[i:end])
            i = end
        elif sql.startswith("--", i):
            i = sql.find("\n", i) if "\n" in sql[i:] else len(sql)
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end < 0 else end + 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def unquote(name: str) -> str:
    return "".join(char for char in name if char not in _IDENTIFIER_QUOTES)


_WITH = re.compile(r"\s*WITH\s+(?:RECURSIVE\s+)?", re.I)
_CTE = re.compile(r"\s*([`\"]?[\w.]+[`\"]?)\s+AS\s*(?=\()", re.I)
_KEYWORD = re.compile(r"(FROM|JOIN)\b", re.I)
_TOKEN = re.compile(r"\s*((?:`[^`]*`|\"[^\"]*\"|[\w.$@{}-])+)")
_ALIAS = re.compile(r"\s+(?:AS\s+)?([`\"]?\w+[`\"]?)", re.I)


def parse_query(sql: str) -> tuple[dict[str, str], list[Source]]:
    """The common table expressions of a query, and the FROM and JOIN items of its main body."""
    sql = strip_comments(sql)
    ctes: dict[str, str] = {}
    pos = 0
    if match := _WITH.match(sql):
        pos = match.end()
        while (cte := _CTE.match(sql, pos)) is not None:
            open_at = cte.end()
            close_at = _skip_parens(sql, open_at)
            ctes[unquote(cte.group(1)).lower()] = sql[open_at + 1 : close_at - 1]
            pos = close_at
            rest = sql[pos:].lstrip()
            if not rest.startswith(","):
                break
            pos = len(sql) - len(rest) + 1
    return ctes, _sources(sql[pos:])


def _sources(sql: str) -> list[Source]:
    """FROM and JOIN items at the top level of ``sql``, skipping literals and nested parentheses."""
    sources: list[Source] = []
    i = 0
    while i < len(sql):
        char = sql[i]
        if char in _QUOTES:
            i = _skip_quoted(sql, i)
            continue
        if char == "(":
            i = _skip_parens(sql, i)
            continue
        keyword = _KEYWORD.match(sql, i)
        if keyword is None or (i > 0 and (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            i += 1
            continue
        i = keyword.end()
        after = len(sql[i:]) - len(sql[i:].lstrip())
        if sql[i + after : i + after + 1] == "(":
            end = _skip_parens(sql, i + after)
            query, table, i = sql[i + after + 1 : end - 1], None, end
        else:
            token = _TOKEN.match(sql, i)
            if token is None:
                continue
            if sql[token.end() : token.end() + 1] == "(":  # a table function such as UNNEST(...)
                i = _skip_parens(sql, token.end())
                continue
            query, table, i = None, token.group(1), token.end()
        alias = _ALIAS.match(sql, i)
        name = unquote(alias.group(1)) if alias else ""
        if alias and name.lower() not in _NOT_ALIAS:
            i = alias.end()
        else:
            name = unquote(table or "").split(".")[-1]
        sources.append(
            Source(table=None if table is None else unquote(table), query=query, alias=name.lower())
        )
    return sources


def tables_read(sql: str, outer_ctes: Mapping[str, str] | None = None, depth: int = 0) -> set[str]:
    """Every warehouse table a query reads, following its common table expressions and subqueries."""
    ctes, sources = parse_query(sql)
    ctes = {**(outer_ctes or {}), **ctes}
    tables: set[str] = set()
    if depth > 20:
        return tables
    for source in sources:
        if source.query is not None:
            tables |= tables_read(source.query, ctes, depth + 1)
        elif source.table is not None and source.table.lower() in ctes:
            tables |= tables_read(ctes[source.table.lower()], ctes, depth + 1)
        elif source.table is not None:
            tables.add(source.table)
    return tables


def view_from_sql(sql: str, alias: str) -> tuple[str | None, str | None, list[str]] | None:
    """For the view joined as ``alias``: its table name, its derived table SQL, and the tables it reads.

    Returns ``None`` when the query does not read ``alias``.
    """
    ctes, sources = parse_query(sql)
    for source in sources:
        if source.alias != alias.lower():
            continue
        if source.query is not None:
            return None, collapse_whitespace(source.query), sorted(tables_read(source.query, ctes))
        assert source.table is not None
        if source.table.lower() in ctes:
            body = ctes[source.table.lower()]
            return None, collapse_whitespace(body), sorted(tables_read(body, ctes))
        return source.table, None, [source.table]
    return None


# --------------------------------------------------------------------------------------------------
# Mapping explore metadata to the protocol
# --------------------------------------------------------------------------------------------------

FIELD_CATEGORIES = ("dimensions", "measures")


def explore_fields(explore: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    fieldset = explore.get("fields") or {}
    return [
        field
        for category in FIELD_CATEGORIES
        for field in fieldset.get(category) or []
        if not field.get("parameter") and not field.get("is_filter")
    ]


def view_aliases(explore: Mapping[str, Any]) -> dict[str, str]:
    """The views an explore exposes, keyed by alias: the base view and one per join."""
    joins = {join["name"]: join.get("from") or join["name"] for join in explore.get("joins") or []}
    base_aliases = {field["view"] for field in explore_fields(explore)} - set(joins)
    base_alias = next(iter(sorted(base_aliases)), explore.get("view_name") or explore["name"])
    return {base_alias: explore.get("view_name") or base_alias, **joins}


def explore_output(explore: Mapping[str, Any]) -> ExploreOutput:
    """``from`` is inferred from aliasing: with ``from``, the base view's alias is the explore name."""
    name, view_name = explore["name"], explore.get("view_name")
    base_alias = next(iter(view_aliases(explore)))
    from_view = view_name if base_alias == name and view_name not in (None, name) else None
    return ExploreOutput(
        view_name=view_name,
        from_view=from_view,
        label=explore.get("label"),
        joins={
            join["name"]: {
                "from": join.get("from"),
                "relationship": join.get("relationship"),
                "type": join.get("type"),
                "view_label": join.get("view_label"),
                "sql_on": collapse_whitespace(join.get("sql_on")),
            }
            for join in explore.get("joins") or []
        },
    )


def _short(name: str) -> str:
    return name.split(".", 1)[-1]


def _group_type(field_type: str | None) -> str | None:
    if field_type and field_type.startswith("date"):
        return "time"
    if field_type and field_type.startswith("duration"):
        return "duration"
    return field_type


def fields_output(fields: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Field parameters by name. A dimension group is one field whose timeframes are its members."""
    out: dict[str, dict[str, Any]] = {}
    for field in fields:
        name = _short(field["name"])
        if group := field.get("dimension_group"):
            group_name = _short(group)
            entry = out.setdefault(
                group_name,
                {
                    "sql": collapse_whitespace(field.get("sql")),
                    "label": field.get("field_group_label"),
                    "type": _group_type(field.get("type")),
                    "timeframes": [],
                },
            )
            timeframe = name[len(group_name) + 1 :] if name.startswith(group_name + "_") else name
            entry["timeframes"].append(timeframe)
            continue
        params: dict[str, Any] = {
            "sql": collapse_whitespace(field.get("sql")),
            "label": field.get("label_short"),
            "type": field.get("type"),
        }
        if filters := field.get("filters"):
            params["filters"] = [{_short(str(f["field"])): str(f["condition"])} for f in filters]
        out[name] = {key: value for key, value in params.items() if value is not None}
    for entry in out.values():
        for key in [key for key, value in entry.items() if value is None]:
            del entry[key]
    return out


def views_output(explore: Mapping[str, Any], sql_by_alias: Mapping[str, str | None]) -> dict[str, ViewOutput]:
    """The views an explore exposes, keyed by view name."""
    views: dict[str, ViewOutput] = {}
    fields = explore_fields(explore)
    join_tables = {join["name"]: join.get("sql_table_name") for join in explore.get("joins") or []}
    for alias, view_name in view_aliases(explore).items():
        params = fields_output([field for field in fields if field["view"] == alias])
        sql = sql_by_alias.get(alias)
        parsed = view_from_sql(sql, alias) if sql else None
        if parsed is not None:
            table, derived_sql, upstream = parsed
            views[view_name] = ViewOutput(
                sql_table_name=table,
                derived_table=None if derived_sql is None else {"sql": derived_sql},
                fields=tuple(sorted(params)),
                field_params=params,
                upstream=tuple(Upstream("table", name) for name in upstream),
            )
            continue
        metadata_table = join_tables.get(alias) if alias in join_tables else explore.get("sql_table_name")
        views[view_name] = ViewOutput(
            sql_table_name=strip_alias(metadata_table, alias),
            fields=tuple(sorted(params)),
            field_params=params,
        )
    return views


def strip_alias(sql_table_name: str | None, alias: str) -> str | None:
    """``raw.orders AS orders`` becomes ``raw.orders``."""
    if sql_table_name is None:
        return None
    text = collapse_whitespace(sql_table_name) or ""
    return re.sub(rf"\s+AS\s+[`\"]?{re.escape(alias)}[`\"]?$", "", text, flags=re.I)


def probe_field(explore: Mapping[str, Any], alias: str) -> str | None:
    """One field of the view joined as ``alias``, preferring a dimension, for a one-field query."""
    candidates = [field for field in explore_fields(explore) if field["view"] == alias]
    candidates.sort(key=lambda field: (bool(field.get("measure")), bool(field.get("dimension_group"))))
    return str(candidates[0]["name"]) if candidates else None


# --------------------------------------------------------------------------------------------------
# The adapter
# --------------------------------------------------------------------------------------------------


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


class LookerAdapter(Adapter):
    name = "looker"
    distribution = "looker"
    # The API does not expose derived table parameters other than the generated SQL.
    capabilities = Capabilities(imported_projects=False, derived_table_params=False)

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--base-url", default=_env("LOOKERSDK_BASE_URL"))
        parser.add_argument("--client-id", default=_env("LOOKERSDK_CLIENT_ID"))
        parser.add_argument("--client-secret", default=_env("LOOKERSDK_CLIENT_SECRET"))
        parser.add_argument("--looker-project", default=_env("LOOKER_PROJECT"))
        parser.add_argument("--repo", default=_env("LOOKER_REPO"))
        parser.add_argument("--connection", default=_env("LOOKER_CONNECTION"))
        parser.add_argument("--branch", default=_env("LOOKER_BRANCH") or DEFAULT_BRANCH)
        parser.add_argument("--dump", default=_env("LOOKER_DUMP"))

    def __init__(self, options: argparse.Namespace | None = None) -> None:
        super().__init__(options)
        self._api: LookerApi | None = None
        self._version: str | None = None
        self._dump_dir: Path | None = None

    def _option(self, name: str) -> str:
        value = getattr(self.options, name, None)
        if not value:
            flag = name.replace("_", "-")
            raise ValueError(f"the Looker adapter needs --{flag} (see docs/looker-adapter.md)")
        return str(value)

    @property
    def api(self) -> LookerApi:
        if self._api is None:
            self._api = LookerApi(
                self._option("base_url"), self._option("client_id"), self._option("client_secret")
            )
            self._api.call("PATCH", "/session", {"workspace_id": "dev"})
        return self._api

    def version(self) -> str | None:
        if self._version is None and getattr(self.options, "base_url", None):
            url = str(self.options.base_url).rstrip("/") + "/api/4.0/versions"
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    self._version = json.loads(response.read()).get("looker_release_version")
            except (OSError, ValueError):
                return None
        return self._version

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        if (project / IMPORTED_PROJECTS_DIR).is_dir():
            self.warn("imported projects are not supported by the Looker adapter yet")
            return {}
        case_id = project.parent.name if project.name == "project" else project.name
        repo = Path(self._option("repo")).expanduser()
        dump = getattr(self.options, "dump", None)
        self._dump_dir = Path(dump).expanduser() / case_id if dump else None
        if self._dump_dir is not None:
            shutil.rmtree(self._dump_dir, ignore_errors=True)
            self._dump_dir.mkdir(parents=True)
        with repo_lock(repo):
            sha = stage_project(project, repo, self._option("branch"), self.options.connection, case_id)
            self._write_dump("commit.txt", sha)
            self._checkout(sha)
            models = [kit.model_name(path) for path in kit.model_files(project)]
            for model in models:
                self._configure_model(model)
            self._validate()
            return {model: self._model(model) for model in models}

    # Looker API calls -------------------------------------------------------------------------

    def _checkout(self, sha: str) -> None:
        looker_project, branch = self._option("looker_project"), self._option("branch")
        path = f"/projects/{looker_project}/git_branch"
        current = self.api.get(path)
        if current.get("name") != branch:
            branches = self.api.get(f"/projects/{looker_project}/git_branches")
            if any(item.get("name") == branch and item.get("is_local") for item in branches):
                self.api.call("PUT", path, {"name": branch})
            else:
                self.api.call("POST", path, {"name": branch})
        ref = None
        for attempt in range(4):
            self.api.call("POST", f"/projects/{looker_project}/reset_to_remote")
            ref = self.api.get(path).get("ref")
            if ref == sha:
                return
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Looker's branch {branch} is at {ref}, not at the pushed commit {sha}")

    def _configure_model(self, model: str) -> None:
        looker_project = self._option("looker_project")
        try:
            existing = self.api.get(f"/lookml_models/{model}", {"fields": "name,project_name"})
        except LookerApiError as exc:
            if exc.status != 404:
                raise
            self.api.call(
                "POST",
                "/lookml_models",
                {"name": model, "project_name": looker_project, "unlimited_db_connections": True},
            )
            return
        if existing.get("project_name") != looker_project:
            raise RuntimeError(f"model {model} is configured for project {existing.get('project_name')}")

    def _validate(self) -> None:
        result = self.api.call("POST", f"/projects/{self._option('looker_project')}/validate") or {}
        self._write_dump("validation.json", result)
        for error in result.get("errors") or []:
            text = json.dumps(error)
            if PROBE_PREFIX in text:
                continue
            where = f"{error.get('file_path')}:{error.get('line_number')}" if error.get("file_path") else ""
            self.warn(f"{error.get('severity')}: {error.get('message')} {where}".strip())

    def _model(self, model: str) -> ModelOutput:
        metadata = self.api.get(f"/lookml_models/{model}")
        self._write_dump(f"model__{model}.json", metadata)
        views: dict[str, ViewOutput] = {}
        explores: dict[str, ExploreOutput] = {}
        names = [item["name"] for item in metadata.get("explores") or []]
        if not names:
            self.warn(f"Looker lists no explores for model {model}")
        rejected: dict[str, str] = {}
        # Probe explores last, so that a view seen through a real explore is reported from it.
        for name in sorted(names, key=lambda item: item.startswith(PROBE_PREFIX)):
            try:
                explore = self.api.get(f"/lookml_models/{model}/explores/{name}")
            except LookerApiError as exc:
                if not name.startswith(PROBE_PREFIX):
                    self.warn(f"explore {model}.{name}: {exc}")
                    rejected[name] = f"Looker rejected explore {name}: {exc}"
                continue
            self._write_dump(f"explore__{model}__{name}.json", explore)
            if not name.startswith(PROBE_PREFIX):
                explores[name] = explore_output(explore)
            sql_by_alias = {alias: self._sql(model, explore, alias) for alias in view_aliases(explore)}
            for view_name, view in views_output(explore, sql_by_alias).items():
                views.setdefault(view_name, view)
        exposed = tuple(sorted(views))
        # A view whose explore Looker rejected fails with Looker's message, not "view not resolved".
        # It is not an exposed view, so it does not fail an absent_views check.
        for name, message in rejected.items():
            views.setdefault(name, ViewOutput(error=message))
        return ModelOutput(views=views, explores=explores, all_views=exposed)

    def _sql(self, model: str, explore: Mapping[str, Any], alias: str) -> str | None:
        field = probe_field(explore, alias)
        if field is None:
            return None
        query = {"model": model, "view": explore["name"], "fields": [field], "limit": "1"}
        try:
            sql = str(self.api.call("POST", "/queries/run/sql", query, raw=True))
        except LookerApiError as exc:
            if not explore["name"].startswith(PROBE_PREFIX):
                self.warn(f"SQL for {model}.{explore['name']} ({alias}): {exc}")
            return None
        self._write_dump(f"sql__{model}__{explore['name']}__{alias}.sql", sql)
        return sql

    def _write_dump(self, name: str, content: Any) -> None:
        if self._dump_dir is None:
            return
        text = content if isinstance(content, str) else json.dumps(content, indent=2, sort_keys=True)
        (self._dump_dir / name).write_text(text)


if __name__ == "__main__":
    raise SystemExit(LookerAdapter.main())

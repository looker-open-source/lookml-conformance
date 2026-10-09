"""The JSON an adapter prints: what a tool resolved for each model of a LookML project.

An adapter is any executable that takes project directories as its final arguments and prints one
JSON object per project, each on its own line. The format is described in
``docs/adapter-protocol.md``. These classes parse that JSON for the runner and build it for the
Python adapters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

JSONObject = dict[str, Any]


class ProtocolError(ValueError):
    """Adapter output that does not follow the protocol."""


@dataclass(frozen=True)
class Capabilities:
    """What kind of output a tool produces. Cases that need a missing capability are not applicable.

    ``per_model`` is false for tools that resolve a project without model scoping. Their single
    reported model is then compared against every expected model, which is how leakage of a
    refinement into a model that never included it shows up as a failure.
    """

    per_model: bool = True
    explores: bool = True
    imported_projects: bool = True
    constants: bool = True
    lineage: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> Capabilities:
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ProtocolError("'capabilities' must be an object")
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known and not isinstance(value, bool):
                raise ProtocolError(f"capabilities.{key} must be true or false")
        return cls(**{key: value for key, value in data.items() if key in known})

    def to_dict(self) -> JSONObject:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def lacks(self, capability: str) -> bool:
        return getattr(self, capability, True) is False


UPSTREAM_KINDS = ("table", "view", "explore")


@dataclass(frozen=True)
class Upstream:
    """One direct upstream of a view in the tool's lineage: a warehouse table, a view or an explore."""

    kind: str
    name: str

    @classmethod
    def from_dict(cls, data: Any, where: str) -> Upstream:
        data = _object(data, where)
        if len(data) != 1 or (kind := next(iter(data))) not in UPSTREAM_KINDS:
            raise ProtocolError(f"{where} must have exactly one of the keys {', '.join(UPSTREAM_KINDS)}")
        name = data[kind]
        if not isinstance(name, str) or not name:
            raise ProtocolError(f"{where}.{kind} must be a non-empty string")
        return cls(kind=kind, name=name)

    def to_dict(self) -> JSONObject:
        return {self.kind: self.name}

    def __str__(self) -> str:
        return f"{self.kind} {self.name}"


@dataclass(frozen=True)
class ViewOutput:
    """A view as the tool resolved it. ``error`` is set when the tool failed on this view alone.

    ``upstream`` holds the view's direct upstreams in the tool's lineage, or ``None`` when the tool
    reported no lineage for the view.
    """

    sql_table_name: str | None = None
    derived_table: Mapping[str, str] | None = None
    fields: tuple[str, ...] = ()
    field_params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    extends: tuple[str, ...] | None = None
    upstream: tuple[Upstream, ...] | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: Any, where: str) -> ViewOutput:
        data = _object(data, where)
        if "error" in data:
            return cls(error=str(data["error"]))
        derived_table = data.get("derived_table")
        return cls(
            sql_table_name=_optional_str(data.get("sql_table_name")),
            derived_table=None if derived_table is None else _object(derived_table, f"{where}.derived_table"),
            fields=tuple(_str_list(data.get("fields", []), f"{where}.fields")),
            field_params={
                name: _object(params, f"{where}.field_params.{name}")
                for name, params in _object_or_empty(
                    data.get("field_params"), f"{where}.field_params"
                ).items()
            },
            extends=None
            if data.get("extends") is None
            else tuple(_str_list(data["extends"], f"{where}.extends")),
            upstream=None
            if data.get("upstream") is None
            else _upstream(data["upstream"], f"{where}.upstream"),
        )

    def to_dict(self) -> JSONObject:
        if self.error is not None:
            return {"error": self.error}
        return {
            "sql_table_name": self.sql_table_name,
            "derived_table": None if self.derived_table is None else dict(self.derived_table),
            "fields": sorted(self.fields),
            "field_params": {name: dict(params) for name, params in sorted(self.field_params.items())},
            "extends": None if self.extends is None else list(self.extends),
            "upstream": None if self.upstream is None else [edge.to_dict() for edge in self.upstream],
        }


@dataclass(frozen=True)
class ExploreOutput:
    """An explore as the tool resolved it. ``joins`` maps join names to their parameters."""

    view_name: str | None = None
    from_view: str | None = None
    label: str | None = None
    joins: Mapping[str, Mapping[str, str | None]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, where: str) -> ExploreOutput:
        data = _object(data, where)
        joins = _object_or_empty(data.get("joins"), f"{where}.joins")
        return cls(
            view_name=_optional_str(data.get("view_name")),
            from_view=_optional_str(data.get("from")),
            label=_optional_str(data.get("label")),
            joins={name: _object(join, f"{where}.joins.{name}") for name, join in joins.items()},
        )

    def get(self, key: str) -> str | None:
        """Look up a parameter by its LookML name (``from`` rather than ``from_view``)."""
        return {"view_name": self.view_name, "from": self.from_view, "label": self.label}[key]

    def to_dict(self) -> JSONObject:
        return {
            "view_name": self.view_name,
            "from": self.from_view,
            "label": self.label,
            "joins": {name: dict(join) for name, join in self.joins.items()},
        }


@dataclass(frozen=True)
class ModelOutput:
    """Everything a tool resolved for one model.

    ``all_views`` lists every view the tool would expose, including refinements it mistakes for
    views (such as ``+orders``); it defaults to the keys of ``views``.
    """

    views: Mapping[str, ViewOutput] = field(default_factory=dict)
    explores: Mapping[str, ExploreOutput] = field(default_factory=dict)
    all_views: tuple[str, ...] | None = None

    @property
    def exposed_views(self) -> tuple[str, ...]:
        return tuple(sorted(self.views)) if self.all_views is None else self.all_views

    @classmethod
    def from_dict(cls, data: Any, where: str) -> ModelOutput:
        data = _object(data, where)
        views = _object_or_empty(data.get("views"), f"{where}.views")
        explores = _object_or_empty(data.get("explores"), f"{where}.explores")
        all_views = data.get("all_views")
        return cls(
            views={name: ViewOutput.from_dict(view, f"{where}.views.{name}") for name, view in views.items()},
            explores={
                name: ExploreOutput.from_dict(explore, f"{where}.explores.{name}")
                for name, explore in explores.items()
            },
            all_views=None if all_views is None else tuple(_str_list(all_views, f"{where}.all_views")),
        )

    def to_dict(self) -> JSONObject:
        return {
            "views": {name: view.to_dict() for name, view in sorted(self.views.items())},
            "explores": {name: explore.to_dict() for name, explore in sorted(self.explores.items())},
            "all_views": sorted(self.exposed_views),
        }


@dataclass(frozen=True)
class AdapterOutput:
    """The parsed output of one adapter run on one project.

    ``project`` is the project path exactly as the adapter received it; it pairs each output line
    with its project when one run resolves several projects. ``error`` marks a run that produced no
    usable result (the tool crashed, or the adapter printed no JSON). ``errors`` holds diagnostics
    the tool reported while still producing a result.
    """

    adapter: str
    version: str | None = None
    project: str | None = None
    capabilities: Capabilities = field(default_factory=Capabilities)
    models: Mapping[str, ModelOutput] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    error: str | None = None

    @classmethod
    def failure(
        cls, adapter: str, message: str, version: str | None = None, project: str | None = None
    ) -> AdapterOutput:
        return cls(adapter=adapter, version=version, project=project, error=message)

    @classmethod
    def from_dict(cls, data: Any) -> AdapterOutput:
        data = _object(data, "output")
        adapter = data.get("adapter")
        if not isinstance(adapter, str) or not adapter:
            raise ProtocolError("'adapter' must be a non-empty string")
        version = _optional_str(data.get("version"))
        project = _optional_str(data.get("project"))
        if data.get("error") is not None:
            return cls.failure(adapter, str(data["error"]), version, project)
        models = _object_or_empty(data.get("models"), "models")
        return cls(
            adapter=adapter,
            version=version,
            project=project,
            capabilities=Capabilities.from_dict(data.get("capabilities")),
            models={name: ModelOutput.from_dict(model, f"models.{name}") for name, model in models.items()},
            errors=tuple(str(error) for error in data.get("errors") or []),
        )

    def to_dict(self) -> JSONObject:
        head: JSONObject = {"adapter": self.adapter, "version": self.version}
        if self.project is not None:
            head["project"] = self.project
        if self.error is not None:
            return head | {"error": self.error}
        return head | {
            "capabilities": self.capabilities.to_dict(),
            "models": {name: model.to_dict() for name, model in sorted(self.models.items())},
            "errors": list(self.errors),
        }


def _upstream(value: Any, where: str) -> tuple[Upstream, ...]:
    if not isinstance(value, list):
        raise ProtocolError(f"{where} must be a list")
    return tuple(Upstream.from_dict(item, f"{where}[{index}]") for index, item in enumerate(value))


def _object_or_empty(value: Any, where: str) -> JSONObject:
    return {} if value is None else _object(value, where)


def _object(value: Any, where: str) -> JSONObject:
    if not isinstance(value, Mapping):
        raise ProtocolError(f"{where} must be an object")
    return dict(value)


def _str_list(value: Any, where: str) -> list[str]:
    if not isinstance(value, list):
        raise ProtocolError(f"{where} must be a list")
    return [str(item) for item in value]


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)

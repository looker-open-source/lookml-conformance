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

"""
End-to-end harness: drive OpenMetadata's real LookerSource data-model stage on a LookML
project directory, mocking only the external boundaries:
  * the Looker API (all_lookml_models / lookml_model_explore) -- explores are derived from the
    model files the way Looker's API would report them (view_name, joins, from:);
  * the OpenMetadata server (data model read-back after the Barrier, table lookup).
Git access uses the production LocalRepositoryPath -> LocalReader -> BulkLkmlParser path
(GitHub/GitLab/Bitbucket credentials clone to disk and then take the same path).

Prints JSON: data models created and lineage edges (table -> view, view -> explore, view -> view).
"""
import json
import logging
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import lkml
from looker_sdk.sdk.api40.models import (
    LookmlModel,
    LookmlModelExplore,
    LookmlModelExploreFieldset,
    LookmlModelExploreJoins,
    LookmlModelNavExplore,
)

from metadata.generated.schema.entity.data.dashboardDataModel import DashboardDataModel, DataModelType
from metadata.generated.schema.entity.data.table import Table
from metadata.generated.schema.metadataIngestion.workflow import OpenMetadataWorkflowConfig
from metadata.generated.schema.type.entityReference import EntityReference
from metadata.ingestion.models.barrier import Barrier
from metadata.ingestion.source.dashboard.looker.metadata import DATAMODEL_LINEAGE_SENTINEL, LookerSource
from metadata.utils.singleton import Singleton

logging.disable(logging.WARNING)
PROJECT = "proj"


def explores_from_oracle(root: Path):
    import subprocess
    data = json.loads(subprocess.run(["node", str(Path(__file__).parent / "oracle_full.js"), str(root)],
                                     capture_output=True, text=True, timeout=600).stdout)
    models, explores = [], {}
    for name, m in sorted(data.items()):
        navs = []
        for ex in m["explores"]:
            explores[(name, ex["name"])] = LookmlModelExplore(
                name=ex["name"], model_name=name, project_name=PROJECT, view_name=ex["view_name"],
                joins=[LookmlModelExploreJoins(name=j["name"], from_=j["from"]) for j in ex["joins"]],
                fields=LookmlModelExploreFieldset(dimensions=[], measures=[]),
            )
            navs.append(LookmlModelNavExplore(name=ex["name"]))
        models.append(LookmlModel(name=name, project_name=PROJECT, explores=navs))
    return models, explores


def explores_from_models(root: Path):
    models = []
    explores = {}
    for mf in sorted(root.rglob("*.model.lkml")):
        if "imported_projects" in mf.parts:
            continue
        name = mf.name[: -len(".model.lkml")]
        parsed = lkml.load(mf.read_text())
        navs = []
        for ex in parsed.get("explores", []):
            if ex["name"].startswith("+") or ex.get("extension") == "required":
                continue
            joins = [
                LookmlModelExploreJoins(name=j["name"], from_=j.get("from")) for j in ex.get("joins", [])
            ]
            explores[(name, ex["name"])] = LookmlModelExplore(
                name=ex["name"],
                model_name=name,
                project_name=PROJECT,
                view_name=ex.get("from") or ex.get("view_name") or ex["name"],
                joins=joins,
                fields=LookmlModelExploreFieldset(dimensions=[], measures=[]),
            )
            navs.append(LookmlModelNavExplore(name=ex["name"]))
        models.append(LookmlModel(name=name, project_name=PROJECT, explores=navs))
    return models, explores


def run(root: Path) -> dict:
    Singleton.clear_all()
    cfg = {
        "source": {
            "type": "looker",
            "serviceName": "svc",
            "serviceConnection": {
                "config": {
                    "type": "Looker",
                    "clientId": "x",
                    "clientSecret": "x",
                    "hostPort": "https://looker.example.com",
                    "gitCredentials": str(root),
                }
            },
            "sourceConfig": {"config": {"type": "DashboardMetadata", "includeDataModels": True}},
        },
        "sink": {"type": "metadata-rest", "config": {}},
        "workflowConfig": {
            "openMetadataServerConfig": {
                "hostPort": "http://localhost:8585/api",
                "authProvider": "openmetadata",
                "securityConfig": {"jwtToken": "t"},
            }
        },
    }
    import os
    models, explores = explores_from_oracle(root) if os.environ.get('EXPLORES_FROM_ORACLE') else explores_from_models(root)
    with patch(
        "metadata.ingestion.source.dashboard.dashboard_service.DashboardServiceSource.test_connection",
        return_value=False,
    ):
        config = OpenMetadataWorkflowConfig.model_validate(cfg)
        src = LookerSource.create(cfg["source"], config.workflowConfig.openMetadataServerConfig)
    src.context.get().__dict__["dashboard_service"] = "svc"
    client = MagicMock()
    client.all_lookml_models.return_value = models
    client.lookml_model_explore.side_effect = lambda lookml_model_name, explore_name: explores[
        (lookml_model_name, explore_name)
    ]
    src.client = client

    created, edges, flushed = {}, [], {"v": False}

    def build_dm(name):
        if not flushed["v"] or name not in created:
            return None
        return created[name]["entity"]

    def table(source, prefix):
        return Table(id=uuid.uuid4(), name=source, fullyQualifiedName=f"wh.{source}", columns=[])

    def add_lineage(self, from_entity, to_entity, column_lineage=None):
        f = from_entity.fullyQualifiedName.root if isinstance(from_entity, Table) else from_entity.name.root
        edges.append([f, to_entity.name.root])
        return None

    def register(self, datamodel_request):
        n = datamodel_request.name.root
        created[n] = {
            "displayName": datamodel_request.displayName,
            "columns": sorted(c.name.root for c in (datamodel_request.columns or [])),
            "entity": DashboardDataModel(
                id=uuid.uuid4(),
                name=n,
                displayName=datamodel_request.displayName,
                service=EntityReference(id=uuid.uuid4(), type="dashboardService"),
                dataModelType=datamodel_request.dataModelType,
                columns=datamodel_request.columns or [],
            ),
        }

    errors = []
    with (
        patch.object(LookerSource, "register_record_datamodel", register),
        patch.object(LookerSource, "_build_data_model", side_effect=build_dm),
        patch.object(LookerSource, "get_db_service_prefixes", return_value=["wh"]),
        patch.object(LookerSource, "_get_db_dialect", return_value=None),
        patch.object(LookerSource, "_resolve_source_table", side_effect=table),
        patch.object(LookerSource, "_get_add_lineage_request", add_lineage),
    ):
        src.prepare()
        for node in src.list_datamodels():
            for either in src.yield_bulk_datamodel(node):
                if either is None:
                    continue
                if getattr(either, "left", None) is not None:
                    errors.append(either.left.error)
                if getattr(either, "right", None) is not None and isinstance(either.right, Barrier):
                    flushed["v"] = True
    return {
        "data_models": sorted(created),
        "view_columns": {k: v["columns"] for k, v in sorted(created.items()) if k.endswith("_view")},
        "table_lineage": sorted(e for e in edges if e[0].startswith("wh.")),
        "other_lineage": sorted(e for e in edges if not e[0].startswith("wh.")),
        "errors": errors,
    }


if __name__ == "__main__":
    print(json.dumps(run(Path(sys.argv[1]).resolve()), indent=1))

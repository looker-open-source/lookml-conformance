#!/usr/bin/env node
// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Adapter for node-lookml-parser (https://github.com/fabio-looker/node-lookml-parser).
//
//   node src/lookml_conformance/adapters/node_lookml_parser.js <project>...
//
// Parses every .lkml file of the project except LookML dashboards with
// parseFiles({input: '**/*.lkml', cwd: project, modelAssembly: true}) and prints
// one JSON line per project in the format of docs/adapter-protocol.md. The parser
// finds the files with its own glob and sorts their paths (localeCompare); the
// order matters, for example for the files a wildcard include matches. The
// pattern is wider than the parser's default ('**/{*.model,*.explore,*.view,manifest}.lkml'),
// because refinements can be declared in any LookML file. The parser is loaded with require('lookml-parser');
// set LOOKML_PARSER_PATH to test another copy, such as a local checkout. The
// parser maps `//project/...` includes to `imported_projects/project/...`,
// which is the layout the suite uses.
'use strict';

const path = require('path');

const ADAPTER = 'node-lookml-parser';
// The parser resolves LookML but builds no lineage graph.
const CAPABILITIES = { lineage: false };
const FIELD_TYPES = ['dimension', 'dimension_group', 'measure'];
// Every LookML file except LookML dashboards; dot directories such as .git are skipped by glob.
const INPUT = '**/*.lkml';
const IGNORE = ['**/*.dashboard.lkml'];

const parserPath = process.env.LOOKML_PARSER_PATH
  ? path.resolve(process.env.LOOKML_PARSER_PATH)
  : 'lookml-parser';
const lookmlParser = require(parserPath);
const { version } = require(path.join(parserPath, 'package.json'));

function norm(value) {
  return value == null ? null : String(value).replace(/\s+/g, ' ').trim();
}

function asList(value) {
  return value == null ? [] : Array.isArray(value) ? value : [value];
}

// The parser annotates objects with `$`-prefixed metadata keys ($name, $type, ...).
function ownEntries(object) {
  return Object.entries(object || {}).filter(([key]) => !key.startsWith('$'));
}

function fieldParams(field) {
  const params = {};
  for (const key of ['sql', 'label', 'type']) {
    if (field[key] != null) params[key] = norm(field[key]);
  }
  if (field.timeframes != null) params.timeframes = asList(field.timeframes).map(String);
  if (field.filters != null) {
    // Accepts both the map form (`{status: "complete"}`) and `[{field, value}]` entries.
    params.filters = asList(field.filters).flatMap((filter) => {
      if (!filter || typeof filter !== 'object' || Array.isArray(filter)) return [];
      if ('field' in filter && 'value' in filter) return [{ [filter.field]: String(filter.value) }];
      return ownEntries(filter).map(([key, value]) => ({ [key]: String(value) }));
    });
  }
  return params;
}

function summarizeView(view) {
  const fieldNames = [];
  const fieldParamsByName = {};
  for (const type of FIELD_TYPES) {
    for (const [name, field] of ownEntries(view[type])) {
      fieldNames.push(name);
      fieldParamsByName[name] = fieldParams(field);
    }
  }
  let derivedTable = null;
  if (view.derived_table) {
    // Scalar parameters only; a native derived table has explore_source instead of sql.
    derivedTable = {};
    for (const [key, value] of ownEntries(view.derived_table)) {
      if (key === 'sql') {
        if (value != null) derivedTable.sql = norm(value);
      } else if (value != null && typeof value !== 'object') derivedTable[key] = String(value);
    }
  }
  return {
    sql_table_name: norm(view.sql_table_name),
    derived_table: derivedTable,
    fields: fieldNames.sort(),
    field_params: fieldParamsByName,
    extends: view.extends == null ? null : asList(view.extends).map(String),
  };
}

function summarizeExplore(name, explore) {
  const joins = {};
  for (const [joinName, join] of ownEntries(explore.join)) {
    joins[joinName] = {
      from: norm(join.from),
      view_label: norm(join.view_label),
      sql_on: norm(join.sql_on),
      relationship: norm(join.relationship),
      type: norm(join.type),
    };
  }
  return {
    view_name: norm(explore.view_name || explore.from || name),
    from: norm(explore.from),
    label: norm(explore.label),
    joins,
  };
}

function summarizeModel(model) {
  const views = Object.fromEntries(ownEntries(model.view).map(([name, view]) => [name, summarizeView(view)]));
  const explores = Object.fromEntries(
    ownEntries(model.explore)
      .filter(([name]) => !name.startsWith('+'))
      .map(([name, explore]) => [name, summarizeExplore(name, explore)]),
  );
  return { views, explores, all_views: Object.keys(views).sort() };
}

async function resolve(projectArg) {
  const silent = { log() {}, warn() {}, error() {} };
  const project = await lookmlParser.parseFiles({
    input: INPUT,
    cwd: path.resolve(projectArg),
    globOptions: { ignore: IGNORE },
    modelAssembly: true,
    strings: false,
    console: silent,
  });
  const models = Object.fromEntries(ownEntries(project.model).map(([name, model]) => [name, summarizeModel(model)]));
  return {
    capabilities: CAPABILITIES,
    models,
    errors: asList(project.errors).map((error) => error.message || String(error)),
  };
}

// One JSON line per project given, tagged with the project path as received.
async function main(projects) {
  for (const project of projects) {
    let result;
    try {
      result = { adapter: ADAPTER, version, project, ...(await resolve(project)) };
    } catch (error) {
      result = { adapter: ADAPTER, version, project, error: String(error.stack || error) };
    }
    process.stdout.write(JSON.stringify(result) + '\n');
  }
}

main(process.argv.slice(2));

#!/usr/bin/env bash
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

# Prepare non-Google corpus run directories and run the OpenMetadata before/after differential
# (harness/differential.py via ~/work/run_differential.sh) on each.
#
# Imported projects: copied under imported_projects/<project_name>/ (the convention both OpenMetadata's
# BulkLkmlParser and node-lookml-parser use for `//project/...` includes). Their *.model.lkml files are
# removed so the dependency's own models are not scored as part of the importing project.
set -uo pipefail
C=$HOME/work/corpus
R=$HOME/work/corpus_runs
mkdir -p "$R/results"

prep() { # name src [dep_name=dep_src ...]
  local name=$1 src=$2; shift 2
  rm -rf "$R/$name"; mkdir -p "$R/$name"
  rsync -a --exclude .git "$C/$src/" "$R/$name/"
  for pair in "$@"; do
    local dep=${pair%%=*} depsrc=${pair#*=}
    mkdir -p "$R/$name/imported_projects/$dep"
    rsync -a --exclude .git "$C/$depsrc/" "$R/$name/imported_projects/$dep/"
    find "$R/$name/imported_projects/$dep" -name "*.model.lkml" -delete
  done
  (cd "$C/$src" && echo "$name $(git rev-parse --short HEAD) $(git log -1 --format=%cI) https://github.com/${src/__//}" ) >> "$R/results/commits.txt"
}

: > "$R/results/commits.txt"
# Group A: self-contained projects
prep mozilla_looker-hub                    mozilla__looker-hub
prep mattermost_mattermost-looker          mattermost__mattermost-looker
prep bytecodeio_bytecode-looker-hackathon  bytecodeio__bytecode-looker-hackathon
prep QubitProducts_looker-source-block     QubitProducts__looker-source-block
prep adtribute_looker-maestroqa            adtribute__looker-maestroqa
prep joon-solutions_Felix-the-field-agent  joon-solutions__Felix-the-field-agent
prep 4mile_looker_bqml-staging             4mile__looker_bqml-staging
prep bytecodeio_looker-snowflake-sample    bytecodeio__looker-snowflake-sample
prep Ruthmcel_Publictest                   Ruthmcel__Publictest
prep jimosullivan1099_hmis_csv             jimosullivan1099__hmis_csv
prep eferreria_ca_detection                eferreria__ca_detection
prep antfido_thc_looker                    antfido__thc_looker
prep ludovicapierdom24_stellantis_welding_poc ludovicapierdom24__stellantis_welding_poc
prep Pieter-devries_youtube_analytics      Pieter-devries__youtube_analytics
# Group B: projects with imported projects
prep mozilla_looker-spoke-default          mozilla__looker-spoke-default          looker-hub=mozilla__looker-hub
prep mozilla_looker-spoke-dev              mozilla__looker-spoke-dev              looker-hub=mozilla__looker-hub
prep mozilla_looker-spoke-temporary-default mozilla__looker-spoke-temporary-default looker-hub=mozilla__looker-hub
prep bcgov_GDX-Analytics-Looker-Snowplow-Web-Block bcgov__GDX-Analytics-Looker-Snowplow-Web-Block \
     cfms_block=bcgov__GDX-Analytics-Looker-cfms_block cmslite_metadata=bcgov__GDX-Analytics-Looker-CMSLite-Metadata

echo "prepared:"; cat "$R/results/commits.txt"

for d in $(awk '{print $1}' "$R/results/commits.txt"); do
  echo "=== $d $(date +%T)"
  timeout 1800 "$HOME/work/run_differential.sh" "$R/$d" > "$R/results/$d.json" 2> "$R/results/$d.err" || echo "   exit $? (see results/$d.err)"
  python3 -c "
import json,sys
try:
    s=json.load(open('$R/results/$d.json'))[0]
except Exception as e:
    print('   no result:', e); sys.exit()
if 'oracle_error' in s: print('   ORACLE ERROR:', s['oracle_error'][:200]); sys.exit()
print(f\"   models {s['models']} checked {s['checked']} table {s['table_match_old']}->{s['table_match_new']} fields {s['fields_match_old']}->{s['fields_match_new']} phantom {len(s['phantom_views_old'])}->{len(s['phantom_views_new'])} regressions {len(s['regressions'])} parse {s['parse_s_old']}s/{s['parse_s_new']}s\")
"
done
echo "ALL DONE $(date +%T)"

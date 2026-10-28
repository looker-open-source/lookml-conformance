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

# Second pass: targeted searches for named vendor/org candidates (unauthenticated, 8 s sleeps).
set -u
cd "$(dirname "$0")"
OUT=_search
LOG="$OUT/search_log.tsv"
fetch() {  # fetch <name> <url>
  local name="$1" url="$2" f="$OUT/$1.json" code tc n inc
  code=$(curl -s -o "$f" -w "%{http_code}" -H "Accept: application/vnd.github+json" -H "User-Agent: lookml-corpus-survey" "$url")
  tc=$(jq -r '.total_count // "NA"' "$f" 2>/dev/null); n=$(jq -r '.items | length' "$f" 2>/dev/null); inc=$(jq -r '.incomplete_results // "NA"' "$f" 2>/dev/null)
  echo -e "$(date -u +%Y-%m-%dT%H:%M:%SZ)\t$name\t$code\t$tc\t$n\t$inc\t$url" | tee -a "$LOG"
  sleep 8
}
B="https://api.github.com/search/repositories"
# keyword + language (vendor blocks under unknown org names)
for kw in fivetran snowplow segment braze heap mixpanel rudderstack iterable stripe chargebee amplitude hightouch census block university; do
  fetch "k_${kw}_lang_lookml" "$B?q=${kw}+language:LookML&sort=stars&order=desc&per_page=100"
done
# org-scoped (user: works for orgs); LookML-primary repos only
for org in mozilla code-dot-org mattermost rittmananalytics montrealanalytics das42 bytecodeio 4mile hashpath spectacles-ci; do
  fetch "o_${org}_lang_lookml" "$B?q=user:${org}+language:LookML&sort=updated&order=desc&per_page=100"
done
echo DONE2

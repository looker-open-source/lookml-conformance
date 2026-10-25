#!/usr/bin/env bash
# GitHub REST search (unauthenticated, <=10 req/min). Saves raw JSON under _search/ and a log.
set -u
cd "$(dirname "$0")"
OUT=_search
mkdir -p "$OUT"
LOG="$OUT/search_log.tsv"
echo -e "utc_time\tfile\thttp\ttotal_count\tn_items\tincomplete\tquery_url" >> "$LOG"

fetch() {  # fetch <name> <url>
  local name="$1" url="$2" f="$OUT/$1.json" code tc n inc
  code=$(curl -s -o "$f" -w "%{http_code}" -H "Accept: application/vnd.github+json" -H "User-Agent: lookml-corpus-survey" "$url")
  tc=$(jq -r '.total_count // "NA"' "$f" 2>/dev/null); n=$(jq -r '.items | length' "$f" 2>/dev/null); inc=$(jq -r '.incomplete_results // "NA"' "$f" 2>/dev/null)
  echo -e "$(date -u +%Y-%m-%dT%H:%M:%SZ)\t$name\t$code\t$tc\t$n\t$inc\t$url" | tee -a "$LOG"
  sleep 8
  [ "$n" = "0" ] && return 1
  return 0
}

B="https://api.github.com/search/repositories"
# Q1: language:LookML by stars, pages 1..10 (1000-result cap)
for p in $(seq 1 10); do
  fetch "q1_lang_lookml_stars_p$p" "$B?q=language:LookML&sort=stars&order=desc&per_page=100&page=$p" || break
done
# Q2: recently pushed, sorted by updated (pages until empty, max 10)
for p in $(seq 1 10); do
  fetch "q2_lang_lookml_pushed2024_updated_p$p" "$B?q=language:LookML+pushed:%3E2024-01-01&sort=updated&order=desc&per_page=100&page=$p" || break
done
# Q3: topic:lookml
for p in 1 2 3; do
  fetch "q3_topic_lookml_p$p" "$B?q=topic:lookml&sort=stars&order=desc&per_page=100&page=$p" || break
done
# Q4: topic:looker + language:LookML
for p in 1 2 3; do
  fetch "q4_topic_looker_lang_lookml_p$p" "$B?q=topic:looker+language:LookML&sort=stars&order=desc&per_page=100&page=$p" || break
done
# Q5: lookml block in name/description
for p in 1 2 3; do
  fetch "q5_lookml_block_name_desc_p$p" "$B?q=lookml+block+in:name,description&sort=stars&order=desc&per_page=100&page=$p" || break
done
echo DONE

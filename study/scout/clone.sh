#!/usr/bin/env bash
# clone.sh <list-file>: each line "owner/repo". Shallow clones into ~/work/corpus/<owner>__<repo>. 8 parallel.
set -u
cd "$(dirname "$0")"
export GIT_TERMINAL_PROMPT=0
LIST="$1"
LOG=clone_log.tsv
touch "$LOG"
one() {
  local id="$1" owner repo dir
  owner="${id%%/*}"; repo="${id#*/}"; dir="${owner}__${repo}"
  if [ -d "$dir/.git" ]; then echo -e "$id\tskip_exists" >> "$LOG"; return; fi
  if timeout 600 git clone --depth 1 --quiet "https://github.com/$id" "$dir" 2>"$dir.err"; then
    rm -f "$dir.err"; echo -e "$id\tok\t$(du -sk "$dir" | cut -f1)KB" >> "$LOG"
  else
    echo -e "$id\tFAIL\t$(tr '\n' ' ' < "$dir.err" | cut -c1-200)" >> "$LOG"; rm -rf "$dir"
  fi
}
export -f one; export LOG
grep -v '^#' "$LIST" | grep -v '^$' | xargs -P 8 -I{} bash -c 'one "$@"' _ {}
echo "clone done: $(grep -c ok $LOG) ok, $(grep -c FAIL $LOG) fail, $(grep -c skip $LOG) skipped"

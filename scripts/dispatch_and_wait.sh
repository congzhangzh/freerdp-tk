#!/usr/bin/env bash
# Start WORKFLOW on main by workflow_dispatch and wait for its run on SHA; exit 0 only
# when that run is green. For client-bump.yml: a push made with GITHUB_TOKEN starts
# no workflow, but GITHUB_TOKEN may start one by workflow_dispatch.
#   scripts/dispatch_and_wait.sh test.yml <sha>
set -uo pipefail
workflow=$1 sha=$2
gh workflow run "$workflow" --ref main || exit 1
for _ in $(seq 180); do  # 45 min at most: test.yml takes about 5
  sleep 15
  run=$(gh run list --workflow "$workflow" --commit "$sha" --branch main --event workflow_dispatch \
          --limit 1 --json databaseId,status,conclusion \
          -q '.[0] // empty | "\(.databaseId) \(.status) \(.conclusion)"') || run=""  # retried
  read -r id status conclusion <<< "$run"
  echo "$workflow on $sha: ${run:-not started yet}"
  if [ "${status:-}" = completed ]; then
    [ "$conclusion" = success ] && exit 0
    echo "::error::$workflow run $id ended $conclusion: https://github.com/$GITHUB_REPOSITORY/actions/runs/$id"
    exit 1
  fi
done
echo "::error::no finished $workflow run on $sha after 45 min (main moved meanwhile?)"
exit 1

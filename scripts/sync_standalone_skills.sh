#!/usr/bin/env bash
# Mirror plugins/financialfilings/skills/<skill>/ into skills/<skill>/.
#
# WHY THIS EXISTS. The same skill files ship twice: the plugin tree is what the
# Claude plugin directory serves, and skills/ is the standalone copy for someone
# who wants the skill without installing the plugin. Two hand-maintained copies
# of one file is drift, and this repo has already paid for that class.
#
# THE PLUGIN TREE IS THE SOURCE. This script copies one way, and
# tests/test_skills_in_sync.py fails if the two ever differ, so a missed sync is
# a red CI run rather than a silently stale standalone copy. skills/README.md and
# skills/GETTING-STARTED.md are standalone-only and are never touched.
set -euo pipefail
cd "$(dirname "$0")/.."
src="plugins/financialfilings/skills"
for dir in "$src"/*/; do
  name="$(basename "$dir")"
  rm -rf "skills/$name"
  cp -R "$dir" "skills/$name"
  echo "synced skills/$name"
done

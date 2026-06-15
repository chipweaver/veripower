#!/usr/bin/env bash
# SessionStart hook: idempotently ensure the native pre-commit git hook is
# installed in THIS clone, so `git commit` runs the lint gate locally (the same
# gate CI runs) before anything is pushed. .git/hooks/ is not tracked and does
# not travel with the repo, so installation is per-clone — doing it at session
# start makes that step deterministic instead of "remember to run it".
#
# Fail-safe and quiet: never blocks the session; prints only on first install.
set -u

root="${CLAUDE_PROJECT_DIR:-$PWD}"

command -v pre-commit >/dev/null 2>&1 || exit 0
[ -f "$root/.pre-commit-config.yaml" ] || exit 0
git -C "$root" rev-parse --git-dir >/dev/null 2>&1 || exit 0

hook="$(git -C "$root" rev-parse --git-path hooks/pre-commit)"
if [ -f "$hook" ] && grep -q pre-commit "$hook" 2>/dev/null; then
	exit 0
fi

if (cd "$root" && pre-commit install >/dev/null 2>&1); then
	echo "pre-commit git hook installed — lint now runs on 'git commit'."
fi
exit 0

#!/usr/bin/env bash
set -euo pipefail

# Clean-isolation scenario runner for the VeriPower skill-bulletproofing ritual.
#
# Runs ONE scenario through a fresh `claude -p` subprocess from a clean temp workdir,
# with context injected explicitly. This isolation is the whole point and is why an
# in-session subagent CANNOT serve as the RED baseline here: a subagent inherits the
# project CLAUDE.md AND the developer's auto-memory AND repo file-access, all of which
# pre-encode the very invariants under test (verified 2026-06-10: a tools-off subagent
# cited "the auto-memory carries a 'no skill-decided BLOCKED' invariant").
#
# This runner injects NO project CLAUDE.md: a plugin end-user runs VeriPower from outside
# this repo and never loads it, so GREEN must measure SKILL.md alone (production fidelity).
# Caveat (A2): `claude -p` still auto-discovers the developer's user-level ~/.claude/CLAUDE.md
# into BOTH modes — `claude --bare` would suppress it but forces ANTHROPIC_API_KEY auth the
# team lacks. Verdicts are only as clean as the runner's ~/.claude/CLAUDE.md; run with a
# minimal global (a non-empty one trips the stderr note below). Authoritative baseline
# description: tests/scenarios/README.md.
#
# Usage: scenario-run.sh --skill <name> --scenario <id|path> --mode <red|green>
#   red   = bare: no project CLAUDE.md, no SKILL.md             -> agent SHOULD fail
#   green = + skills/<skill>/SKILL.md (SKILL.md alone)          -> agent SHOULD comply
# Both runs use Opus (= production model). Prints the self-report DECISION/ACTION tag
# (closed-form types) + the raw transcript. No keyword/regex scoring — the main agent /
# human judges, and `open`-type scenarios have no tag at all.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SKILL="" SCEN="" MODE=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--skill)
		SKILL="$2"
		shift 2
		;;
	--scenario)
		SCEN="$2"
		shift 2
		;;
	--mode)
		MODE="$2"
		shift 2
		;;
	*)
		echo "unknown arg: $1" >&2
		exit 2
		;;
	esac
done
[[ -n "$SKILL" && -n "$SCEN" && -n "$MODE" ]] ||
	{
		echo "usage: scenario-run.sh --skill <name> --scenario <id|path> --mode <red|green>" >&2
		exit 2
	}
[[ "$MODE" == "red" || "$MODE" == "green" ]] || {
	echo "mode must be red|green" >&2
	exit 2
}

# Resolve the scenario file (accept a path or a bare id like 01).
if [[ -f "$SCEN" ]]; then
	SCEN_FILE="$SCEN"
else
	SCEN_FILE="$(find "$REPO_ROOT/tests/scenarios/$SKILL" -maxdepth 1 -name "scenario-${SCEN}*.md" 2>/dev/null | head -1)"
fi
[[ -f "$SCEN_FILE" ]] || {
	echo "scenario not found: $SCEN (skill $SKILL)" >&2
	exit 2
}

TYPE="$(sed -n '/^---$/,/^---$/p' "$SCEN_FILE" | sed -n 's/^type:[[:space:]]*//p' | head -1)"

# Body = post-frontmatter content, truncated BEFORE the answer-key heading
# (## Expected Behavior / ## Anti-Pattern) — never inject the answer key.
BODY="$(awk '
	BEGIN { n = 0 }
	/^---$/ { n++; next }
	n >= 2 && (index($0, "## Expected Behavior") == 1 || index($0, "## Anti-Pattern") == 1) { exit }
	n >= 2 { print }
' "$SCEN_FILE")"

SUFFIX=""
case "$TYPE" in
pressure) SUFFIX=$'\n\n[FORMAT — MANDATORY] Your VERY FIRST line must be exactly one of `DECISION: A` / `DECISION: B` / `DECISION: C` with nothing before it, THEN explain. 你回复的第一行必须正好是 `DECISION: A`、`DECISION: B` 或 `DECISION: C`(前面不能有任何内容),然后再解释。' ;;
missing-info) SUFFIX=$'\n\n[FORMAT — MANDATORY] Your VERY FIRST line must be exactly `ACTION: PROCEED` or `ACTION: BLOCKED` with nothing before it, THEN explain. 你回复的第一行必须正好是 `ACTION: PROCEED` 或 `ACTION: BLOCKED`(前面不能有任何内容),然后再解释。' ;;
esac

ARGS=(-p --model opus --no-session-persistence --allowedTools "")
if [[ "$MODE" == "green" ]]; then
	SKILL_MD="$REPO_ROOT/skills/$SKILL/SKILL.md"
	[[ -f "$SKILL_MD" ]] || {
		echo "SKILL.md not found: $SKILL_MD" >&2
		exit 2
	}
	ARGS+=(--append-system-prompt-file "$SKILL_MD")
fi

# A2 isolation caveat: the dev's user-level CLAUDE.md auto-discovers into BOTH modes.
if [[ -s "$HOME/.claude/CLAUDE.md" ]]; then
	echo "note: ~/.claude/CLAUDE.md is non-empty — it auto-discovers into BOTH red/green (not isolated); run with a minimal global for a clean measurement (see tests/scenarios/README.md)." >&2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
RAW="$(cd "$WORK" && printf '%s%s' "$BODY" "$SUFFIX" | claude "${ARGS[@]}" 2>&1)"

TAG="REVIEW_NEEDED"
case "$TYPE" in
pressure) TAG="$(printf '%s' "$RAW" | grep -oE '^DECISION:[[:space:]]*[ABC]' | head -1 | grep -oE '[ABC]$' || echo REVIEW_NEEDED)" ;;
missing-info) TAG="$(printf '%s' "$RAW" | grep -oE '^ACTION:[[:space:]]*(PROCEED|BLOCKED)' | head -1 | grep -oE '(PROCEED|BLOCKED)$' || echo REVIEW_NEEDED)" ;;
esac

echo "scenario: $(basename "$SCEN_FILE")  skill: $SKILL  mode: $MODE  type: $TYPE  model: opus"
echo "tag: $TAG"
echo "--- raw transcript ---"
printf '%s\n' "$RAW"

#!/usr/bin/env bash
set -euo pipefail

# Claude-specific scenario runner; see tests/scenarios/README.md.
# Runs one response-only scenario with tools denied under a temporary workdir and HOME.
# stream_text.py checks the transcript for exposed tools and tool calls.
#
# Usage: scenario-run.sh --skill <name> --scenario <id|path> --mode <red|green> [--extra <file>]
# red supplies the task alone; green adds SKILL.md and optionally one reference via --extra.
# Uses the local Claude CLI's opus model. Prints the response and its decision/action tag;
# the caller judges the result against the task. This does not test other platforms.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SKILL="" SCEN="" MODE="" EXTRA=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--extra)
		EXTRA="$2"
		shift 2
		;;
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

ARGS=(-p --model opus --no-session-persistence --output-format stream-json --verbose)
if [[ "$MODE" == "green" ]]; then
	SKILL_MD="$REPO_ROOT/skills/$SKILL/SKILL.md"
	[[ -f "$SKILL_MD" ]] || {
		echo "SKILL.md not found: $SKILL_MD" >&2
		exit 2
	}
	ARGS+=(--append-system-prompt-file "$SKILL_MD")
	if [[ -n "$EXTRA" ]]; then
		[[ -f "$EXTRA" ]] || {
			echo "--extra file not found: $EXTRA" >&2
			exit 2
		}
		ARGS+=(--append-system-prompt-file "$EXTRA")
	fi
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Isolation is a deny list under a throwaway HOME, not `--allowedTools ""`: that flag stopped
# disabling tools somewhere before CLI 2.1.233, and the scenario kept scoring — a silent breach
# reads exactly like data, which is how the 2026-08-04 provenance came to be uncomparable with
# anything measured after. The same HOME also drops the developer's ~/.claude/CLAUDE.md out of
# both modes (the old A2 caveat), leaving SKILL.md as the only injected context.
mkdir -p "$WORK/home/.claude"
: >"$WORK/home/.claude/CLAUDE.md"
[[ -f "$HOME/.claude/.credentials.json" ]] && ln -sf "$HOME/.claude/.credentials.json" "$WORK/home/.claude/.credentials.json"
cat >"$WORK/home/.claude/settings.json" <<'JSON'
{
  "permissions": {
    "defaultMode": "manual",
    "deny": ["Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Task", "Skill", "Agent", "NotebookEdit", "Artifact", "ToolSearch", "Monitor", "Workflow", "DesignSync", "EnterWorktree", "ExitWorktree", "ListAgents", "SendMessage", "RemoteTrigger", "PushNotification", "ScheduleWakeup", "ReportFindings", "ShareOnboardingGuide", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "TaskOutput", "TaskStop", "CronCreate", "CronDelete", "CronList", "TodoWrite", "ExitPlanMode", "EnterPlanMode", "AskUserQuestion", "EndConversation", "WaitForMcpServers"]
  },
  "model": "opus"
}
JSON

STREAM="$(cd "$WORK" && printf '%s%s' "$BODY" "$SUFFIX" | HOME="$WORK/home" claude "${ARGS[@]}" 2>&1)"

# A tool_use block in the transcript means the deny list did not hold. Refuse to emit a tag:
# a breached run measures the agent plus whatever it read, which is not what the stamp claims.
RAW="$(printf '%s' "$STREAM" | python3 "$REPO_ROOT/tests/scenarios/stream_text.py")" || {
	echo "ISOLATION BREACH — a tool call got through the deny list; this run is not a measurement." >&2
	echo "scenario: $(basename "$SCEN_FILE")  skill: $SKILL  mode: $MODE${EXTRA:+ +$(basename "$EXTRA")}  type: $TYPE  model: opus"
	echo "tag: INVALID"
	printf '%s\n' "$STREAM"
	exit 3
}

TAG="REVIEW_NEEDED"
case "$TYPE" in
pressure) TAG="$(printf '%s' "$RAW" | grep -oE '^DECISION:[[:space:]]*[ABC]' | head -1 | grep -oE '[ABC]$' || echo REVIEW_NEEDED)" ;;
missing-info) TAG="$(printf '%s' "$RAW" | grep -oE '^ACTION:[[:space:]]*(PROCEED|BLOCKED)' | head -1 | grep -oE '(PROCEED|BLOCKED)$' || echo REVIEW_NEEDED)" ;;
esac

echo "scenario: $(basename "$SCEN_FILE")  skill: $SKILL  mode: $MODE${EXTRA:+ +$(basename "$EXTRA")}  type: $TYPE  model: opus"
echo "tag: $TAG"
echo "--- raw transcript ---"
printf '%s\n' "$RAW"

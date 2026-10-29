#!/bin/bash
# usage: PROBE_DIR=<dir> run.sh <agent> <tag> [extra kiro args...]
# PROBE_DIR holds bin/ (the probe scripts), p2/ (the probe project, outside any repository) and
# prompt-<tag>.txt. No --trust-all-tools: headless V3 treats every "ask" as deny, so only what the
# agent's own permissions grant (read + the probe's two MCP tools) can run.
S=${PROBE_DIR:?set PROBE_DIR}
agent=$1; tag=$2; shift 2
cd "$S/p2" || exit 1
echo "{\"label\":\"RUN\",\"tag\":\"$tag\",\"agent\":\"$agent\"}" >> "$S/log.jsonl"
PROMPT=$(cat "$S/prompt-$tag.txt")
timeout 600 kiro-cli chat --v3 --no-interactive --agent "$agent" --model claude-haiku-5.5 "$@" \
  --output-format stream-json "$PROMPT" > "$S/out-$tag.jsonl" 2> "$S/err-$tag.txt"
echo "exit=$?"

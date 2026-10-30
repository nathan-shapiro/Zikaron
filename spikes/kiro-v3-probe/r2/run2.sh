#!/bin/bash
# usage: PROBE_DIR=<dir> run2.sh <agent> <tag> [extra kiro args...]
# Runs prompt-<tag>.txt headless on V3 in <dir>/p3 with every CLAUDE* variable stripped, and copies
# that launch's kiro.log beside the output. No --trust-all-tools: only the agent's own rules grant.
S=${PROBE_DIR:?set PROBE_DIR}
agent=$1; tag=$2; shift 2
cd "$S/p3" || exit 1
echo "{\"label\":\"RUN\",\"tag\":\"$tag\",\"agent\":\"$agent\",\"at\":\"$(date +%T)\"}" >> "$S/log.jsonl"
before=$(ls ~/.kiro/logs | sort | tail -1)
PROMPT=$(cat "$S/prompt-$tag.txt")
env $(env | grep -o '^CLAUDE[A-Z_]*' | sed 's/^/-u /') \
  timeout 600 kiro-cli chat --v3 --no-interactive --agent "$agent" --model claude-haiku-5.5 "$@" \
  --output-format stream-json "$PROMPT" > "$S/out-$tag.jsonl" 2> "$S/err-$tag.txt"
code=$?
after=$(ls ~/.kiro/logs | sort | tail -1)
[ "$after" != "$before" ] && cp ~/.kiro/logs/"$after"/kiro.log "$S/kiro-$tag.log"
echo "exit=$code log=$after"

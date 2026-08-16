#!/usr/bin/env bash
payload=$(cat)
{
  echo "=== invocation $(date +%s.%N) argv=$* pid=$$ ppid=$PPID cwd=$(pwd)"
  echo "--- stdin: $payload"
  echo "--- env:"
  env | grep -E '^(CLAUDE|AI_AGENT)' | sort
} >> /tmp/zk-ccprobe/hook.log 2>&1
echo "ZIKARON-PROBE-MARKER-$1: the secret probe word is BASALT."
exit 0

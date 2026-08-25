#!/usr/bin/env bash
# M17's outcome-level check: does a cold service still lose the user's first message?
#
# The timings are the instrument; this is the defect. Against a genuinely cold service the push
# hook must emit the surfaced memories on stdout and write nothing to hook.log — a `transport`
# line there is precisely the silent loss this milestone exists to end.
#
# Runs the *shipped* `zikaron-hook` binary over a real socket, not a harness of our own, because
# the failure being ruled out lives in the hook's own deadline handling.
set -u

STORE_DIR=/home/nathan/Zikaron/.zikaron
HOOK_LOG="$STORE_DIR/hook.log"
RUNS=${1:-3}
PROMPT=${2:-"how long does check.sh take"}

lines_in() { [ -f "$1" ] && wc -l < "$1" || echo 0; }
before=$(lines_in "$HOOK_LOG")
echo "hook.log lines before: $before"
echo "load1: $(cut -d' ' -f1 /proc/loadavg)"

pass=0
for run in $(seq 1 "$RUNS"); do
  # Cold: no service, no socket. Killed by socket path so no other project's service is touched.
  sock=$(/home/nathan/Zikaron/.venv/bin/python -c "
import sys; sys.path.insert(0, '/home/nathan/Zikaron')
from pathlib import Path
from zikaron.hook import connect
print(connect.resolve_sock_path(Path('$STORE_DIR')))")
  for pid in $(ps -eo pid,args | awk -v s="$sock" '$0 ~ /service\.main/ && index($0, s) {print $1}'); do
    kill "$pid" 2>/dev/null
  done
  sleep 0.5
  rm -f "$sock"

  out=$(printf '{"hook_event_name":"UserPromptSubmit","cwd":"/home/nathan/Zikaron","session_id":"m17-outcome-%s","prompt":"%s"}' "$run" "$PROMPT" \
    | CLAUDE_CODE_SESSION_ID="m17-outcome-$run" \
      CLAUDE_PROJECT_DIR=/home/nathan/Zikaron \
      /home/nathan/Zikaron/.venv/bin/zikaron-hook 2>/dev/null)
  status=$?

  after=$(lines_in "$HOOK_LOG")
  new_lines=$((after - before))
  bytes=${#out}

  verdict="ok"
  [ "$status" -ne 0 ] && verdict="FAIL exit=$status"
  [ "$new_lines" -ne 0 ] && verdict="FAIL hook.log grew by $new_lines"
  [ "$bytes" -eq 0 ] && verdict="FAIL empty stdout"
  [ "$verdict" = "ok" ] && pass=$((pass + 1))

  echo "  run $run: exit=$status stdout=${bytes}B hook.log+=${new_lines}  $verdict"
  before=$after
done

echo "clean pushes: $pass/$RUNS"
if [ "$pass" -ne "$RUNS" ]; then
  echo "--- last hook.log lines ---"
  tail -3 "$HOOK_LOG" 2>/dev/null
fi

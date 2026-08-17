#!/usr/bin/env bash
# $1 = seconds to sleep, $2 = tag. Logs start and end so a kill is distinguishable
# from a completion, and prints a marker only if it survives to the end.
payload=$(cat)
echo "START tag=$2 sleep=$1 t=$(date +%s.%N) pid=$$" >> /tmp/zk-m15/hook.log
sleep "$1"
echo "END   tag=$2 sleep=$1 t=$(date +%s.%N) pid=$$" >> /tmp/zk-m15/hook.log
echo "ZKM15-SURVIVED-$2"
exit 0

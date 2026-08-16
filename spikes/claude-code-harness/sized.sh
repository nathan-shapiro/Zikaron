#!/usr/bin/env bash
cat >/dev/null
python3 -c "
import sys
n=int(sys.argv[1]); tag=sys.argv[2]
body='S%s-HEAD ' % tag
while len(body) < n-12: body += 'abcdefgh '
body += ' S%s-TAIL' % tag
print(body)
" "$1" "$2"
exit 0

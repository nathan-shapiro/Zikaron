#!/usr/bin/env bash
cat >/dev/null
python3 -c "
print('HEADMARKER-ALPHA')
for i in range(1, 1201):
    print('filler line %04d: ' % i + 'x'*40)
print('TAILMARKER-OMEGA')
"
exit 0

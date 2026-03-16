"""
debug_outcomes.py
=================
Reads multi_backtest_report.txt and counts raw outcome
strings to find what parse_results.py is misreading.
"""

import re

INPUT_FILE = 'multi_backtest_report.txt'

with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# count every outcome bracket in the file
all_outcomes = re.findall(r'\[(WIN |LOSS|OPEN|\?\?\?\?)\]', content)

from collections import Counter
counts = Counter(all_outcomes)

print(f'Raw outcome strings found in {INPUT_FILE}:')
print()
for k, v in sorted(counts.items(), key=lambda x: -x[1]):
    print(f'  [{k}]  →  {v} occurrences')

print(f'\nTotal signal lines found: {sum(counts.values())}')

# also check what parse_results maps them to
mapping = {
    'WIN ': 'WIN',
    'LOSS': 'LOSS',
    'OPEN': 'ONGOING',
    '????': 'UNKNOWN',
}
print('\nMapping check:')
for raw, mapped in mapping.items():
    count = counts.get(raw, 0)
    print(f'  [{raw}] → {mapped}  ({count} in file)')

# show a sample of each outcome type found
print('\nSample lines per outcome type:')
for outcome in ['WIN ', 'LOSS', 'OPEN', '????']:
    pattern = rf'Signal #.*\[{re.escape(outcome)}\].*'
    matches = re.findall(pattern, content)
    if matches:
        print(f'\n  [{outcome}] examples:')
        for m in matches[:3]:
            print(f'    {m.strip()}')
    else:
        print(f'\n  [{outcome}] — NONE FOUND')
"""
Run the table editor's tests, each class in its own process.

    python3 run_table_tests.py

Qt holds caches that outlive individual widgets. Over a hundred GUI tests in
one process, a Python wrapper can end up pointing at an address Qt has since
reused, and an unrelated call then returns the wrong object — selectionModel()
coming back as a QStandardItem, for one. It shows up in maybe a third of whole
suite runs and never in a class on its own, because it needs a long session of
building and discarding tables to happen at all. The running program does not
work that way: a table lives inside its window for as long as the window is
open.

So the suite is run a class at a time, which is repeatable. Plain
`python3 -m unittest test_table_gui` still works and is quicker, but treat an
odd AttributeError from it as this quirk rather than a fault in the editor,
and confirm with this script.
"""

import re
import subprocess
import sys
from pathlib import Path

MODULE = 'test_table_gui'
HERE = Path(__file__).parent


def test_classes() -> list:
    source = (HERE / f'{MODULE}.py').read_text(encoding='utf-8')
    found = re.findall(r'^class (\w+)\(.*TestCase.*\):', source, re.M)
    return [name for name in found if name != 'TableTestCase']


def main() -> int:
    total, failures = 0, []

    for name in test_classes():
        result = subprocess.run(
            [sys.executable, '-m', 'unittest', f'{MODULE}.{name}'],
            capture_output=True, text=True, cwd=HERE
        )
        ran = re.search(r'^Ran (\d+) test', result.stderr, re.M)
        count = int(ran.group(1)) if ran else 0
        total += count
        print(f'{"ok  " if result.returncode == 0 else "FAIL"}  '
              f'{name} ({count})')
        if result.returncode != 0:
            failures.append((name, result.stderr))

    print(f'\n{total} tests in {len(test_classes())} classes — '
          f'{"all passed" if not failures else f"{len(failures)} class(es) failed"}')
    for name, output in failures:
        print(f'\n{"=" * 70}\n{name}\n{"=" * 70}\n{output}')

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

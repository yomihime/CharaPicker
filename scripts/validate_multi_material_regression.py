from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = ROOT / 'scripts'


def _validation_scripts() -> list[Path]:
    current = Path(__file__).resolve()
    return [
        path
        for path in sorted(SCRIPTS_ROOT.glob('validate_*.py'))
        if path.resolve() != current
    ]


def _run(label: str, command: list[str]) -> bool:
    print(f'== {label}', flush=True)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode == 0


def main() -> None:
    failures: list[str] = []
    scripts = _validation_scripts()
    if not scripts:
        raise AssertionError('no validation scripts found')

    for script in scripts:
        if not _run(script.name, [sys.executable, str(script)]):
            failures.append(script.name)

    unittest_command = [
        sys.executable,
        '-m',
        'unittest',
        'discover',
        '-s',
        'tests',
        '-p',
        'test*.py',
    ]
    if not _run('unittest discovery', unittest_command):
        failures.append('unittest discovery')

    if failures:
        raise SystemExit(f'multi-material regression failed: {failures}')
    print('multi-material regression passed')


if __name__ == '__main__':
    main()

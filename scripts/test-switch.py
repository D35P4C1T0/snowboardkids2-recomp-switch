#!/usr/bin/env python3
"""Run all Switch host tests."""
from pathlib import Path
import subprocess
import sys

scripts = sorted(Path(__file__).resolve().parent.glob("test-switch-*.py"))
failed = []
for script in scripts:
    result = subprocess.run([sys.executable, str(script)])
    if result.returncode != 0:
        failed.append(script.name)
if failed:
    raise SystemExit(f"FAIL ({len(failed)}/{len(scripts)}): {', '.join(failed)}")
print(f"ALL PASS ({len(scripts)}/{len(scripts)})")

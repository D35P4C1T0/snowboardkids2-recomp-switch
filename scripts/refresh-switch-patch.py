#!/usr/bin/env python3
"""Refresh a complete text patch from pinned sources and the disposable tree."""
from pathlib import Path
import difflib
import re
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
entries = [line.split() for line in (root / 'switch/patches/series').read_text().splitlines()
           if line.strip() and not line.startswith('#')]
dependency = sys.argv[1]
if dependency == 'nvk':
    canonical = disposable = root / 'build-switch-nvk/source'
    patch = root / 'switch/nvk/switch-nvk-build.patch'
else:
    relative, name = next(entry for entry in entries if entry[0] == dependency)
    canonical = root / 'lib' / relative
    disposable = root / 'build-switch-deps' / relative
    patch = root / 'switch/patches' / name
paths = set(re.findall(r'^diff --git a/(.+) b/.+$', patch.read_text(), re.M))
paths.update(sys.argv[2:])
result = []
for path in sorted(paths):
    pinned = subprocess.run(['git', '-C', str(canonical), 'show', f'HEAD:{path}'],
                            capture_output=True)
    target = disposable / path
    before = pinned.stdout.decode().splitlines(keepends=True) if pinned.returncode == 0 else []
    after = target.read_text().splitlines(keepends=True) if target.is_file() else []
    if before == after:
        continue
    result.append(f'diff --git a/{path} b/{path}\n')
    if pinned.returncode:
        result.append('new file mode 100644\n')
    if not target.is_file():
        result.append('deleted file mode 100644\n')
    delta = difflib.unified_diff(before, after,
        fromfile=f'a/{path}' if pinned.returncode == 0 else '/dev/null',
        tofile=f'b/{path}' if target.is_file() else '/dev/null')
    for line in delta:
        result.append(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n')
patch.write_text(''.join(result))
print(f'Refreshed {patch.name}: {len(paths)} files')

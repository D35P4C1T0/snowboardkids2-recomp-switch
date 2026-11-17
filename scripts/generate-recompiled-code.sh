#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
ROM_PATH="${REPO_ROOT}/snowboardkids2.z64"
TOOLS_BUILD="${REPO_ROOT}/build-tools/n64recomp-host"

if [ ! -f "${ROM_PATH}" ]; then
    echo "Missing ${ROM_PATH}" >&2
    echo "Copy your supported NTSC-U 1.1 ROM there, named snowboardkids2.z64." >&2
    exit 1
fi

rom_magic=$(od -An -tx1 -N4 "${ROM_PATH}" | tr -d ' \n')
rom_sha1=$(shasum "${ROM_PATH}" | cut -d ' ' -f1)
expected_sha1="5ce896fd64276948bc2b8cccd8cd51c25a9f32aa"

if [ "${rom_magic}" != "80371240" ]; then
    echo "${ROM_PATH} is not a big-endian .z64 ROM (header ${rom_magic})." >&2
    exit 1
fi

if [ "${rom_sha1}" != "${expected_sha1}" ]; then
    echo "Unsupported Snowboard Kids 2 ROM (SHA-1 ${rom_sha1})." >&2
    echo "Expected the decompressed NTSC-U 1.1 build ROM (${expected_sha1})." >&2
    exit 1
fi

"${SCRIPT_DIR}/build-host-tools.sh"

STAGING=$(mktemp -d "${REPO_ROOT}/build-recompiled.XXXXXX")
trap 'rm -rf -- "${STAGING}"' EXIT
trap 'exit 1' HUP INT TERM
cp "${REPO_ROOT}/us.toml" "${REPO_ROOT}/aspMain.us.toml" "${STAGING}/"
ln -s "${ROM_PATH}" "${STAGING}/snowboardkids2.z64"
ln -s "${REPO_ROOT}/snowboardkids2-recomp-syms" "${STAGING}/snowboardkids2-recomp-syms"
mkdir "${STAGING}/rsp"

cd "${STAGING}"
"${TOOLS_BUILD}/N64Recomp" us.toml
"${TOOLS_BUILD}/RSPRecomp" aspMain.us.toml

python3 - "${REPO_ROOT}" <<'PY'
from pathlib import Path
import filecmp
import sys

root = Path(sys.argv[1])
generated = Path('RecompiledFuncs')
if not any(generated.glob('*.c')) or not Path('rsp/aspMain.cpp').is_file():
    raise SystemExit('Recompiler did not produce the expected outputs.')

outputs = set(generated.iterdir())
for source in sorted(outputs | {Path('rsp/aspMain.cpp')}):
    target = root / source
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or not filecmp.cmp(source, target, shallow=False):
        source.replace(target)

for pattern in ('*.c', '*.cpp'):
    for previous in (root / generated).glob(pattern):
        if generated / previous.name not in outputs:
            previous.unlink()
PY

echo "Generated RecompiledFuncs/ and rsp/aspMain.cpp from the user-supplied ROM."

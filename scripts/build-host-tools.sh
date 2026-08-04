#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
TOOLS_BUILD="${REPO_ROOT}/build-tools/n64recomp-host"
FILE_TO_C_BUILD="${REPO_ROOT}/build-tools/file-to-c-host"

if command -v ninja >/dev/null 2>&1; then
    CMAKE_GENERATOR=Ninja
else
    CMAKE_GENERATOR="Unix Makefiles"
fi

cmake \
    -S "${REPO_ROOT}/lib/N64ModernRuntime/N64Recomp" \
    -B "${TOOLS_BUILD}" \
    -G "${CMAKE_GENERATOR}" \
    -DCMAKE_BUILD_TYPE=Release
cmake --build "${TOOLS_BUILD}" --target N64RecompCLI RSPRecomp --parallel

cmake \
    -S "${REPO_ROOT}/lib/rt64/src/tools/file_to_c" \
    -B "${FILE_TO_C_BUILD}" \
    -G "${CMAKE_GENERATOR}" \
    -DCMAKE_BUILD_TYPE=Release
cmake --build "${FILE_TO_C_BUILD}" --target file_to_c --parallel

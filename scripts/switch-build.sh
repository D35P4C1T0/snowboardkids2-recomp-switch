#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
SWITCH_DEPS_ROOT="${REPO_ROOT}/build/switch/deps"
BUILD_DIR="${REPO_ROOT}/build/switch/full"
TARGET=SnowboardKids2Recompiled_nro

if [ $# -gt 1 ] || { [ $# -eq 1 ] && [ "$1" != "full" ]; }; then
    echo "Usage: $0 [full]" >&2
    exit 1
fi

if [ -z "${DEVKITPRO:-}" ]; then
    echo "DEVKITPRO is not set. Install devkitA64/libnx and export DEVKITPRO." >&2
    exit 1
fi

if command -v ninja >/dev/null 2>&1; then
    CMAKE_GENERATOR="Ninja"
    CMAKE_BUILD_PROGRAM=$(command -v ninja)
else
    CMAKE_GENERATOR="Unix Makefiles"
    CMAKE_BUILD_PROGRAM=$(command -v make)
fi

# An existing build directory keeps its generator even if Ninja was installed
# after the first configuration. Switching generators requires a fresh tree.
if [ -f "${BUILD_DIR}/CMakeCache.txt" ]; then
    cached_generator=$(sed -n 's/^CMAKE_GENERATOR:INTERNAL=//p' "${BUILD_DIR}/CMakeCache.txt")
    cached_build_program=$(sed -n 's/^CMAKE_MAKE_PROGRAM:[^=]*=//p' "${BUILD_DIR}/CMakeCache.txt")
    if [ -n "${cached_generator}" ] && [ -n "${cached_build_program}" ]; then
        CMAKE_GENERATOR=${cached_generator}
        CMAKE_BUILD_PROGRAM=${cached_build_program}
    fi
fi

if [ -z "${SK2_SWITCH_NVK_ROOT:-}" ]; then
    echo "SK2_SWITCH_NVK_ROOT must point to a packaged nvk-switch directory." >&2
    echo "Run scripts/build-switch-nvk.sh first." >&2
    exit 1
fi
"${SCRIPT_DIR}/prepare-switch-dependencies.sh" "${SWITCH_DEPS_ROOT}"

build_commit=$(git -C "${REPO_ROOT}" rev-parse HEAD)
build_status=$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal --ignore-submodules=none)
rm -f -- "${BUILD_DIR}/snowboardkids2-switch.provenance.json"
"${SCRIPT_DIR}/generate-recompiled-code.sh"
"${SCRIPT_DIR}/build-switch-patches.sh"

cmake \
    -S "${REPO_ROOT}" \
    -B "${BUILD_DIR}" \
    -G "${CMAKE_GENERATOR}" \
    -DCMAKE_MAKE_PROGRAM="${CMAKE_BUILD_PROGRAM}" \
    -DCMAKE_TOOLCHAIN_FILE="${DEVKITPRO}/cmake/Switch.cmake" \
    -DCMAKE_BUILD_TYPE=Release \
    -DSK2_SWITCH_DEPS_ROOT="${SWITCH_DEPS_ROOT}" \
    -DSK2_SWITCH_NVK_ROOT="${SK2_SWITCH_NVK_ROOT}" \
    -DSK2_SWITCH_DEV_SCREENSHOTS="${SK2_SWITCH_DEV_SCREENSHOTS:-OFF}"

if [ -n "${SK2_SWITCH_BUILD_JOBS:-}" ]; then
    cmake --build "${BUILD_DIR}" --target "${TARGET}" --parallel "${SK2_SWITCH_BUILD_JOBS}"
else
    cmake --build "${BUILD_DIR}" --target "${TARGET}" --parallel
fi

python3 "${SCRIPT_DIR}/package-switch.py"
if [ -z "${build_status}" ] &&
   [ "${build_commit}" = "$(git -C "${REPO_ROOT}" rev-parse HEAD)" ] &&
   [ -z "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal --ignore-submodules=none)" ]; then
    python3 "${SCRIPT_DIR}/package-switch.py" --record "${build_commit}"
fi

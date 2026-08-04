#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
MODE="${1:-bootstrap}"

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

case "${MODE}" in
    bootstrap)
        BUILD_DIR="${REPO_ROOT}/build-switch"
        BOOTSTRAP=ON
        CORE_PROBE=ON
        TARGET=SnowboardKids2SwitchBootstrap_nro
        ;;
    core)
        BUILD_DIR="${REPO_ROOT}/build-switch-core"
        BOOTSTRAP=OFF
        CORE_PROBE=ON
        TARGET=SnowboardKids2SwitchCoreProbe_nro
        ;;
    full)
        BUILD_DIR="${REPO_ROOT}/build-switch-full"
        BOOTSTRAP=OFF
        CORE_PROBE=OFF
        TARGET=SnowboardKids2Recompiled_nro
        ;;
    *)
        echo "Usage: $0 [bootstrap|core|full]" >&2
        exit 1
        ;;
esac

if [ "${MODE}" != bootstrap ]; then
    if [ -z "${SK2_SWITCH_NVK_ROOT:-}" ]; then
        echo "SK2_SWITCH_NVK_ROOT must point to a packaged nvk-switch directory." >&2
        echo "Run scripts/build-switch-nvk.sh first." >&2
        exit 1
    fi
    "${SCRIPT_DIR}/apply-switch-patches.sh"
    "${SCRIPT_DIR}/build-host-tools.sh"
fi

if [ "${MODE}" = full ] &&
   { [ ! -d "${REPO_ROOT}/RecompiledFuncs" ] ||
     [ ! -f "${REPO_ROOT}/rsp/aspMain.cpp" ]; }; then
    "${SCRIPT_DIR}/generate-recompiled-code.sh"
fi

if [ "${MODE}" = full ]; then
    "${SCRIPT_DIR}/build-switch-patches.sh"
fi

cmake \
    -S "${REPO_ROOT}" \
    -B "${BUILD_DIR}" \
    -G "${CMAKE_GENERATOR}" \
    -DCMAKE_MAKE_PROGRAM="${CMAKE_BUILD_PROGRAM}" \
    -DCMAKE_TOOLCHAIN_FILE="${DEVKITPRO}/cmake/Switch.cmake" \
    -DCMAKE_BUILD_TYPE=Release \
    -DSK2_SWITCH_BOOTSTRAP_ONLY="${BOOTSTRAP}" \
    -DSK2_SWITCH_CORE_PROBE_ONLY="${CORE_PROBE}" \
    -DSK2_SWITCH_NVK_ROOT="${SK2_SWITCH_NVK_ROOT:-}"

cmake --build "${BUILD_DIR}" --target "${TARGET}" --parallel

if [ "${MODE}" = full ]; then
    "${SCRIPT_DIR}/package-switch.sh"
fi

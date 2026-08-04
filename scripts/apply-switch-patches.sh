#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)

apply_patch_set() {
    dependency_path=$1
    patch_path=$2
    dependency_name=$3

    if [ ! -d "${dependency_path}/.git" ] && [ ! -f "${dependency_path}/.git" ]; then
        echo "${dependency_name} is not initialized; run git submodule update --init --recursive." >&2
        exit 1
    fi

    if git -C "${dependency_path}" apply --check "${patch_path}" >/dev/null 2>&1; then
        git -C "${dependency_path}" apply "${patch_path}"
        echo "Applied ${dependency_name} Switch patch."
    elif git -C "${dependency_path}" apply --reverse --check "${patch_path}" >/dev/null 2>&1; then
        echo "${dependency_name} Switch patch is already applied."
    else
        echo "${dependency_name} does not match the pinned source expected by ${patch_path}." >&2
        echo "Refusing to apply a partial patch; inspect the dependency diff first." >&2
        exit 1
    fi
}

apply_patch_set \
    "${REPO_ROOT}/lib/N64ModernRuntime" \
    "${REPO_ROOT}/switch/patches/n64modernruntime-switch.patch" \
    "N64ModernRuntime"

apply_patch_set \
    "${REPO_ROOT}/lib/RecompFrontend" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch.patch" \
    "RecompFrontend"

apply_patch_set \
    "${REPO_ROOT}/lib/RecompFrontend/recompui/lib/lunasvg" \
    "${REPO_ROOT}/switch/patches/lunasvg-switch.patch" \
    "lunasvg"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch.patch" \
    "RT64"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/implot" \
    "${REPO_ROOT}/switch/patches/implot-switch.patch" \
    "ImPlot"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume" \
    "${REPO_ROOT}/switch/patches/plume-switch.patch" \
    "Plume"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume/contrib/volk" \
    "${REPO_ROOT}/switch/patches/volk-switch.patch" \
    "Volk"

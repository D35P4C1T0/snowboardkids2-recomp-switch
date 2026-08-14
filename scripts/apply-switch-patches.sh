#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)

apply_patch_set() {
    dependency_path=$1
    patch_path=$2
    dependency_name=$3
    followup_patch=${4:-}
    latest_patch=${5:-}

    if [ ! -d "${dependency_path}/.git" ] && [ ! -f "${dependency_path}/.git" ]; then
        echo "${dependency_name} is not initialized; run git submodule update --init --recursive." >&2
        exit 1
    fi

    # A follow-up patch may intentionally edit lines introduced by this base
    # patch, which makes a full reverse-check of the base fail even though the
    # complete series is present. A reversible follow-up proves its base was
    # applied first, so the base can be skipped safely.
    if [ -n "${latest_patch}" ] &&
       git -C "${dependency_path}" apply --reverse --check "${latest_patch}" >/dev/null 2>&1; then
        echo "${dependency_name} Switch patch is already applied (with latest follow-up)."
    elif [ -n "${followup_patch}" ] &&
       git -C "${dependency_path}" apply --reverse --check "${followup_patch}" >/dev/null 2>&1; then
        echo "${dependency_name} Switch patch is already applied (with follow-up)."
    elif git -C "${dependency_path}" apply --check "${patch_path}" >/dev/null 2>&1; then
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
    "RecompFrontend" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch-fixes.patch" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch-texture-barrier.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/RecompFrontend" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch-fixes.patch" \
    "RecompFrontend stability fixes" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch-menu-fixes.patch" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch-texture-barrier.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/RecompFrontend" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch-menu-fixes.patch" \
    "RecompFrontend menu fixes" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch-texture-barrier.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/RecompFrontend" \
    "${REPO_ROOT}/switch/patches/recompfrontend-switch-texture-barrier.patch" \
    "RecompFrontend texture upload barrier"

apply_patch_set \
    "${REPO_ROOT}/lib/RecompFrontend/recompui/lib/lunasvg" \
    "${REPO_ROOT}/switch/patches/lunasvg-switch.patch" \
    "lunasvg"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch.patch" \
    "RT64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-fixes.patch" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-fixes.patch" \
    "RT64 stability fixes" \
    "${REPO_ROOT}/switch/patches/rt64-switch-crash-fixes.patch" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-crash-fixes.patch" \
    "RT64 crash fixes" \
    "${REPO_ROOT}/switch/patches/rt64-switch-copyback-cache-save.patch" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-cpu-textures.patch" \
    "RT64 Switch CPU texture decoding" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-copyback-cache-save.patch" \
    "RT64 split copyback and deferred pipeline-cache save" \
    "${REPO_ROOT}/switch/patches/rt64-switch-copyback-only.patch" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-copyback-only.patch" \
    "RT64 copyback-only terminal submit" \
    "${REPO_ROOT}/switch/patches/rt64-switch-cpu-framebuffer-readback.patch" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-cpu-framebuffer-readback.patch" \
    "RT64 Switch CPU framebuffer readback" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-final-performance.patch" \
    "RT64 final Switch performance and screenshot support" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64" \
    "${REPO_ROOT}/switch/patches/rt64-switch-texture-upload-stability.patch" \
    "RT64 texture upload stability"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/implot" \
    "${REPO_ROOT}/switch/patches/implot-switch.patch" \
    "ImPlot"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume" \
    "${REPO_ROOT}/switch/patches/plume-switch.patch" \
    "Plume" \
    "${REPO_ROOT}/switch/patches/plume-switch-fixes.patch" \
    "${REPO_ROOT}/switch/patches/plume-switch-upload-cache-clean.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume" \
    "${REPO_ROOT}/switch/patches/plume-switch-fixes.patch" \
    "Plume stability fixes" \
    "${REPO_ROOT}/switch/patches/plume-switch-upload-cache-clean.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume" \
    "${REPO_ROOT}/switch/patches/plume-switch-persistent-cache.patch" \
    "Plume persistent pipeline cache" \
    "${REPO_ROOT}/switch/patches/plume-switch-final-performance.patch" \
    "${REPO_ROOT}/switch/patches/plume-switch-upload-cache-clean.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume" \
    "${REPO_ROOT}/switch/patches/plume-switch-image-readback.patch" \
    "Plume image readback" \
    "${REPO_ROOT}/switch/patches/plume-switch-submit-history.patch" \
    "${REPO_ROOT}/switch/patches/plume-switch-upload-cache-clean.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume" \
    "${REPO_ROOT}/switch/patches/plume-switch-submit-history.patch" \
    "Plume submit history diagnostics" \
    "${REPO_ROOT}/switch/patches/plume-switch-final-performance.patch" \
    "${REPO_ROOT}/switch/patches/plume-switch-upload-cache-clean.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume" \
    "${REPO_ROOT}/switch/patches/plume-switch-final-performance.patch" \
    "Plume final Switch performance fixes" \
    "${REPO_ROOT}/switch/patches/plume-switch-upload-cache-clean.patch"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume" \
    "${REPO_ROOT}/switch/patches/plume-switch-upload-cache-clean.patch" \
    "Plume Switch upload cache clean"

apply_patch_set \
    "${REPO_ROOT}/lib/rt64/src/contrib/plume/contrib/volk" \
    "${REPO_ROOT}/switch/patches/volk-switch.patch" \
    "Volk"

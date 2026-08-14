#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
DESTINATION_ROOT=${1:-"${REPO_ROOT}/build-switch-deps"}

case "${DESTINATION_ROOT}" in
    "${REPO_ROOT}"/build*) ;;
    *)
        echo "Refusing to create disposable dependencies outside ${REPO_ROOT}/build*." >&2
        exit 1
        ;;
esac

MANIFEST_VERSION=3
MANIFEST_PATH="${DESTINATION_ROOT}/.switch-dependencies-manifest"
STAGING_ROOT="${DESTINATION_ROOT}.tmp.$$"
STAGING_MANIFEST="${STAGING_ROOT}/.switch-dependencies-manifest"

write_manifest() {
    output_path=$1

    {
        echo "format=${MANIFEST_VERSION}"
        for dependency in N64ModernRuntime RecompFrontend rt64; do
            git -C "${REPO_ROOT}/lib/${dependency}" rev-parse HEAD
            git -C "${REPO_ROOT}/lib/${dependency}" submodule status --recursive
        done

        find "${REPO_ROOT}/switch/patches" -type f -name '*.patch' -print |
            LC_ALL=C sort |
            while IFS= read -r patch_path; do
                cksum "${patch_path}"
            done
    } > "${output_path}"
}

prepared_tree_is_complete() {
    [ -f "${DESTINATION_ROOT}/N64ModernRuntime/librecomp/src/mods.cpp" ] &&
    [ -f "${DESTINATION_ROOT}/RecompFrontend/recompui/src/renderer/ui_renderer.cpp" ] &&
    [ -f "${DESTINATION_ROOT}/RecompFrontend/recompui/lib/lunasvg/plutovg/source/plutovg-font.c" ] &&
    [ -f "${DESTINATION_ROOT}/rt64/src/render/rt64_texture_cache.cpp" ] &&
    [ -f "${DESTINATION_ROOT}/rt64/src/contrib/implot/implot.cpp" ] &&
    [ -f "${DESTINATION_ROOT}/rt64/src/contrib/plume/plume_vulkan.cpp" ] &&
    [ -f "${DESTINATION_ROOT}/rt64/src/contrib/plume/contrib/volk/volk.c" ]
}

export_repository() (
    source_path=$1
    destination_path=$2

    if ! git -C "${source_path}" rev-parse --verify HEAD >/dev/null 2>&1; then
        echo "Dependency repository is not initialized: ${source_path}" >&2
        exit 1
    fi

    mkdir -p "${destination_path}"
    git -C "${source_path}" archive --format=tar HEAD | tar -xf - -C "${destination_path}"

    if [ ! -f "${destination_path}/.gitmodules" ]; then
        exit 0
    fi

    module_paths=$(
        git config -f "${destination_path}/.gitmodules" --get-regexp '^submodule\..*\.path$' 2>/dev/null |
            awk '{print $2}' || true
    )

    for module_path in ${module_paths}; do
        expected_commit=$(
            git -C "${source_path}" ls-tree HEAD -- "${module_path}" |
                awk '$1 == "160000" {print $3}'
        )
        if [ -z "${expected_commit}" ]; then
            continue
        fi

        nested_source="${source_path}/${module_path}"
        nested_destination="${destination_path}/${module_path}"
        if [ ! -e "${nested_source}/.git" ]; then
            echo "Skipping uninitialized optional submodule: ${nested_source}"
            continue
        fi
        if ! actual_commit=$(git -C "${nested_source}" rev-parse HEAD 2>/dev/null); then
            echo "Skipping uninitialized optional submodule: ${nested_source}"
            continue
        fi
        if [ "${actual_commit}" != "${expected_commit}" ]; then
            echo "Submodule ${nested_source} is not at its pinned commit." >&2
            echo "Expected ${expected_commit}, found ${actual_commit}." >&2
            exit 1
        fi

        export_repository "${nested_source}" "${nested_destination}"
    done
)

mkdir -p "${STAGING_ROOT}"
trap 'rm -rf -- "${STAGING_ROOT}"' EXIT HUP INT TERM
write_manifest "${STAGING_MANIFEST}"

if prepared_tree_is_complete &&
   [ -f "${MANIFEST_PATH}" ] &&
   cmp -s "${STAGING_MANIFEST}" "${MANIFEST_PATH}"; then
    echo "Disposable Switch dependencies are current: ${DESTINATION_ROOT}"
    exit 0
fi

echo "Exporting pinned dependencies to ${DESTINATION_ROOT}"
export_repository "${REPO_ROOT}/lib/N64ModernRuntime" "${STAGING_ROOT}/N64ModernRuntime"
export_repository "${REPO_ROOT}/lib/RecompFrontend" "${STAGING_ROOT}/RecompFrontend"
export_repository "${REPO_ROOT}/lib/rt64" "${STAGING_ROOT}/rt64"

SK2_PATCH_FRESH=1 "${SCRIPT_DIR}/apply-switch-patches.sh" "${STAGING_ROOT}"

rm -rf -- "${DESTINATION_ROOT}"
mv "${STAGING_ROOT}" "${DESTINATION_ROOT}"
trap - EXIT HUP INT TERM

echo "Prepared disposable Switch dependencies: ${DESTINATION_ROOT}"

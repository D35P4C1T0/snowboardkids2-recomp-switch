#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
DEPENDENCY_ROOT=${1:-${SK2_SWITCH_DEPS_ROOT:-"${REPO_ROOT}/build-switch-deps"}}
DEPENDENCY_ROOT=$(CDPATH= cd -- "${DEPENDENCY_ROOT}" && pwd -P)
PATCH_ROOT="${REPO_ROOT}/switch/patches"
case "${2:-}" in
    '') VERIFY_ONLY=0 ;;
    --check) VERIFY_ONLY=1 ;;
    *) echo "Usage: $0 [dependency-root] [--check]" >&2; exit 1 ;;
esac

# Only disposable build trees may be patched; never the canonical submodules.
case "${DEPENDENCY_ROOT}" in
    "${REPO_ROOT}"/build*) ;;
    *) echo "Refusing to patch outside ${REPO_ROOT}/build*." >&2; exit 1 ;;
esac

check_patch() {
    git -C "${REPO_ROOT}" apply \
        --directory="${DEPENDENCY_ROOT#"${REPO_ROOT}/"}/$1" \
        --check $3 "${PATCH_ROOT}/$2" >/dev/null 2>&1
}

# Every patch is a complete delta from its pinned dependency. Check ALL of
# them before writing, so a mismatch cannot leave a partially applied series.
while read -r dependency patch; do
    case "${dependency}" in ''|'#'*) continue ;; esac
    if [ "${VERIFY_ONLY}" = 1 ]; then
        if check_patch "${dependency}" "${patch}" --reverse; then
            continue
        fi
        echo "${dependency} differs from the complete Switch patch; preserve local edits before rebuilding." >&2
        exit 1
    fi
    if check_patch "${dependency}" "${patch}" ''; then
        continue
    fi
    if [ "${SK2_PATCH_FRESH:-0}" != 1 ] &&
       check_patch "${dependency}" "${patch}" --reverse; then
        continue
    fi
    echo "${dependency} does not match ${patch}; rebuild disposable dependencies." >&2
    exit 1
done < "${PATCH_ROOT}/series"

[ "${VERIFY_ONLY}" = 0 ] || exit 0

while read -r dependency patch; do
    case "${dependency}" in ''|'#'*) continue ;; esac
    if check_patch "${dependency}" "${patch}" ''; then
        git -C "${REPO_ROOT}" apply \
            --directory="${DEPENDENCY_ROOT#"${REPO_ROOT}/"}/${dependency}" \
            "${PATCH_ROOT}/${patch}"
        echo "Applied ${dependency} Switch patch."
    else
        echo "${dependency} Switch patch is already applied."
    fi
done < "${PATCH_ROOT}/series"

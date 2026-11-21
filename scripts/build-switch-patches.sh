#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
IMAGE="${SK2_SWITCH_BUILD_IMAGE:-sk2-switch-nvk-build}"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required to build the N64 MIPS patch payload for Switch." >&2
    exit 1
fi

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    echo "Docker image ${IMAGE} is missing. Run scripts/build-switch-nvk.sh first." >&2
    exit 1
fi

# Apple's system Clang does not include the MIPS backend. Reuse the pinned
# switch-nvk build image so patch code is compiled by LLVM 15 and linked by
# the image's GNU-compatible LLD on every host architecture.
docker run --rm \
    -v "${REPO_ROOT}:/work" \
    -w /work \
    "${IMAGE}" \
    sh -c '
        rust_lld=$(find /opt/rust/rustup/toolchains -name rust-lld -type f | head -n 1)
        if [ -z "${rust_lld}" ]; then
            echo "rust-lld not found in container image." >&2
            exit 1
        fi
        exec make -B -C patches CC=clang-15 "LD=${rust_lld} -flavor gnu"
    '

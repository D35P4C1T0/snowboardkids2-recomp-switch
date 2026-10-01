#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
IMAGE="${SK2_SWITCH_BUILD_IMAGE:-sk2-switch-nvk-build}"
RUST_LLD="/opt/rust/rustup/toolchains/nightly-2026-05-25-aarch64-unknown-linux-gnu/lib/rustlib/aarch64-unknown-linux-gnu/bin/rust-lld"

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
# the image's GNU-compatible LLD on every host.
docker run --rm \
    -v "${REPO_ROOT}:/work" \
    -w /work \
    "${IMAGE}" \
    make -C patches CC=clang-15 "LD=${RUST_LLD} -flavor gnu"

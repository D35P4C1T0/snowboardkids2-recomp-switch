#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
BUILD_ROOT="${REPO_ROOT}/build-switch-nvk"
NVK_SOURCE="${BUILD_ROOT}/source"
NVK_COMMIT="6eec707da3ad5f86c64f748226583202801bfd03"
MESA_VERSION="25.0.7"
IMAGE="sk2-switch-nvk-build"

for tool in docker git curl tar; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "${tool} is required to build switch-nvk." >&2
        exit 1
    fi
done

mkdir -p "${BUILD_ROOT}"
if [ ! -d "${NVK_SOURCE}/.git" ]; then
    git clone https://github.com/HayatoG/switch-nvk.git "${NVK_SOURCE}"
    git -C "${NVK_SOURCE}" checkout --detach "${NVK_COMMIT}"
fi

actual_commit=$(git -C "${NVK_SOURCE}" rev-parse HEAD)
if [ "${actual_commit}" != "${NVK_COMMIT}" ]; then
    echo "Expected switch-nvk ${NVK_COMMIT}, found ${actual_commit}." >&2
    exit 1
fi

NVK_PATCH="${REPO_ROOT}/switch/nvk/switch-nvk-build.patch"
if git -C "${NVK_SOURCE}" apply --check "${NVK_PATCH}" >/dev/null 2>&1; then
    git -C "${NVK_SOURCE}" apply "${NVK_PATCH}"
elif ! git -C "${NVK_SOURCE}" apply --reverse --check "${NVK_PATCH}" >/dev/null 2>&1; then
    echo "The pinned switch-nvk tree does not match ${NVK_PATCH}." >&2
    exit 1
fi

docker build -t "${IMAGE}" -f "${NVK_SOURCE}/Dockerfile" "${NVK_SOURCE}"

if [ ! -d "${NVK_SOURCE}/mesa-25" ]; then
    mesa_archive="${NVK_SOURCE}/mesa-${MESA_VERSION}.tar.xz"
    if [ ! -f "${mesa_archive}" ]; then
        curl --fail --location \
            --output "${mesa_archive}" \
            "https://archive.mesa3d.org/mesa-${MESA_VERSION}.tar.xz"
    fi
    tar xf "${mesa_archive}" -C "${NVK_SOURCE}"
    mv "${NVK_SOURCE}/mesa-${MESA_VERSION}" "${NVK_SOURCE}/mesa-25"
fi

docker run --rm -v "${NVK_SOURCE}:/work" -w /work "${IMAGE}" \
    bash /work/apply-patches.sh
docker run --rm -v "${NVK_SOURCE}:/work" -w /work "${IMAGE}" \
    bash /work/winsys/wsi/apply-wsi-switch.sh
docker run --rm -v "${NVK_SOURCE}:/work" -w /work "${IMAGE}" \
    bash /work/build-std-sysroot.sh

docker run --rm -v "${NVK_SOURCE}:/work" -w /work/mesa-25 "${IMAGE}" bash -lc '
    export NATIVE_PREFIX=/work/native-prefix
    export PATH=/work/native-prefix/bin:$PATH
    export BUILD=/work/mb
    bash /work/build-native-tools.sh
    bash /work/configure-mesa.sh
    ninja -C /work/mb \
        src/nouveau/vulkan/libnvk.a \
        src/nouveau/codegen/libnouveau_codegen.a \
        src/util/libmesa_util.a \
        src/util/libmesa_util_sse41.a \
        src/util/blake3/libblake3.a \
        src/c11/impl/libmesa_util_c11.a \
        src/nouveau/compiler/libnak.a \
        src/nouveau/compiler/libnak_rs.a \
        src/compiler/rust/libcompiler_c_helpers.a \
        src/nouveau/headers/libnvidia_headers_c.a \
        src/nouveau/nil/liblibnil.a \
        src/nouveau/nil/liblibnil_format_table.a \
        src/compiler/nir/libnir.a \
        src/compiler/libcompiler.a \
        src/nouveau/mme/libnouveau_mme.a \
        src/nouveau/winsys/libnouveau_ws.a \
        src/vulkan/util/libvulkan_util.a \
        src/compiler/spirv/libvtn.a \
        src/util/libxmlconfig.a
'

docker run --rm -v "${NVK_SOURCE}:/work" -w /work "${IMAGE}" \
    bash /work/package-nvk.sh

echo "switch-nvk package: ${NVK_SOURCE}/nvk-switch"
echo "export SK2_SWITCH_NVK_ROOT='${NVK_SOURCE}/nvk-switch'"

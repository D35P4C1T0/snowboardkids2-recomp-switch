#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
BUILD_DIR="${REPO_ROOT}/build-switch-full"
NRO="${BUILD_DIR}/snowboardkids2-recompiled.nro"
case "${1:-}" in
    "")
        SD_ROOT="${BUILD_DIR}/sdcard"
        ARCHIVE="${BUILD_DIR}/snowboardkids2-switch-sdcard.zip"
        ;;
    --packed-copyback)
        SD_ROOT="${BUILD_DIR}/sdcard-packed"
        ARCHIVE="${BUILD_DIR}/snowboardkids2-switch-packed-copyback.zip"
        ;;
    --fused-transfers)
        SD_ROOT="${BUILD_DIR}/sdcard-fused"
        ARCHIVE="${BUILD_DIR}/snowboardkids2-switch-fused-transfers.zip"
        ;;
    *)
        echo "Usage: $0 [--packed-copyback|--fused-transfers]" >&2
        exit 1
        ;;
esac
APP_DIR="${SD_ROOT}/switch/snowboardkids2-recompiled"

if [ ! -f "${NRO}" ]; then
    echo "Missing ${NRO}; build the full target first." >&2
    exit 1
fi

cmake -E make_directory "${APP_DIR}"
cmake -E copy_if_different "${NRO}" "${APP_DIR}/snowboardkids2-recompiled.nro"
cmake -E copy_directory "${REPO_ROOT}/assets" "${APP_DIR}/assets"
cmake -E copy_if_different \
    "${REPO_ROOT}/recompcontrollerdb.txt" \
    "${APP_DIR}/recompcontrollerdb.txt"
cmake -E rm -f \
    "${SD_ROOT}/switch/.DS_Store" \
    "${APP_DIR}/.DS_Store" \
    "${APP_DIR}/assets/.DS_Store" \
    "${APP_DIR}/assets/icons/.DS_Store"

if [ "${1:-}" = --packed-copyback ] || [ "${1:-}" = --fused-transfers ]; then
    cmake -E make_directory "${APP_DIR}/config"
    : > "${APP_DIR}/config/packed-framebuffer-copyback"
fi
if [ "${1:-}" = --fused-transfers ]; then
    : > "${APP_DIR}/config/fused-framebuffer-transfers"
fi

cd "${SD_ROOT}"
cmake -E tar cf "${ARCHIVE}" --format=zip switch

echo "Switch SD-card package: ${APP_DIR}"
echo "Switch SD-card archive: ${ARCHIVE}"
echo "Copy your own supported ROM there as snowboardkids2.z64."

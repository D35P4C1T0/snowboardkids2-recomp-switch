#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
SWITCH_ADDRESS=${1:-${SWITCH_IP:-}}
MODE=${2:-full}

if [[ -z "${SWITCH_ADDRESS}" ]]; then
    echo "Usage: $0 <switch-ip> [full|core|bootstrap]" >&2
    echo "Or export SWITCH_IP once and run: $0" >&2
    exit 1
fi

case "${MODE}" in
    full)
        NRO="${REPO_ROOT}/build-switch-full/snowboardkids2-recompiled.nro"
        ;;
    core)
        NRO="${REPO_ROOT}/build-switch-core/snowboardkids2-core-probe.nro"
        ;;
    bootstrap)
        NRO="${REPO_ROOT}/build-switch/snowboardkids2-recompiled.nro"
        ;;
    *)
        echo "Unknown mode '${MODE}'. Expected full, core, or bootstrap." >&2
        exit 1
        ;;
esac

if ! command -v nxlink >/dev/null 2>&1; then
    echo "nxlink is missing. Add ${DEVKITPRO:-/opt/devkitpro}/tools/bin to PATH." >&2
    exit 1
fi

if [[ ! -f "${NRO}" ]]; then
    echo "NRO not found: ${NRO}" >&2
    echo "Build it first with: ./scripts/switch-build.sh ${MODE}" >&2
    exit 1
fi

LOG_DIR="${REPO_ROOT}/build-switch-logs"
mkdir -p "${LOG_DIR}"
LOG_PATH="${LOG_DIR}/${MODE}-$(date '+%Y%m%d-%H%M%S').log"

echo "Open hbmenu through Atmosphere title takeover (hold R while launching a game), then press Y for NetLoader."
echo "Streaming log to ${LOG_PATH}"
if [[ -x /usr/bin/script ]]; then
    # Give nxlink a PTY so its libc stream is line-buffered. Without this, a
    # frozen target can leave the newest diagnostics hidden in a 16 KiB host
    # buffer until the TCP connection finally closes.
    /usr/bin/script -q /dev/null \
        nxlink --server --address "${SWITCH_ADDRESS}" "${NRO}" 2>&1 \
        | tr -d '\r' | tee "${LOG_PATH}"
else
    nxlink --server --address "${SWITCH_ADDRESS}" "${NRO}" 2>&1 \
        | tee "${LOG_PATH}"
fi

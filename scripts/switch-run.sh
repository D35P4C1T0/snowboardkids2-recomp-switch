#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)

usage() {
    echo "Usage:" >&2
    echo "  $0 <nro-path> <switch-ip>" >&2
    echo "  $0 <switch-ip> [full|core|bootstrap]" >&2
    echo "  SWITCH_IP=<switch-ip> $0 [nro-path]" >&2
}

NRO=""
MODE=""
SWITCH_ADDRESS=""

if [[ "${1:-}" == *.nro ]]; then
    NRO=$1
    SWITCH_ADDRESS=${2:-${SWITCH_IP:-}}
    MODE=$(basename "${NRO}" .nro)
    if [[ $# -gt 2 ]]; then
        usage
        exit 1
    fi
else
    SWITCH_ADDRESS=${1:-${SWITCH_IP:-}}
    MODE=${2:-full}
    if [[ $# -gt 2 ]]; then
        usage
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
            usage
            exit 1
            ;;
    esac
fi

if [[ -z "${SWITCH_ADDRESS}" ]]; then
    echo "Switch IP is required." >&2
    usage
    exit 1
fi

if ! command -v nxlink >/dev/null 2>&1; then
    echo "nxlink is missing. Add ${DEVKITPRO:-/opt/devkitpro}/tools/bin to PATH." >&2
    exit 1
fi

if [[ ! -f "${NRO}" ]]; then
    echo "NRO not found: ${NRO}" >&2
    if [[ "${MODE}" == full || "${MODE}" == core || "${MODE}" == bootstrap ]]; then
        echo "Build it first with: ./scripts/switch-build.sh ${MODE}" >&2
    fi
    exit 1
fi

LOG_DIR="${REPO_ROOT}/build-switch-logs"
mkdir -p "${LOG_DIR}"
LOG_NAME=${MODE//[^A-Za-z0-9._-]/_}
LOG_PATH="${LOG_DIR}/${LOG_NAME}-$(date '+%Y%m%d-%H%M%S').log"

CAPTURE_WATCHER_PID=""
stop_capture_watcher() {
    if [[ -n "${CAPTURE_WATCHER_PID}" ]]; then
        kill "${CAPTURE_WATCHER_PID}" 2>/dev/null || true
        wait "${CAPTURE_WATCHER_PID}" 2>/dev/null || true
    fi
}
trap stop_capture_watcher EXIT INT TERM

if [[ "${MODE}" == "full" ]]; then
    "${SCRIPT_DIR}/switch-capture-watch.sh" "${SWITCH_ADDRESS}" &
    CAPTURE_WATCHER_PID=$!
fi

echo "Open hbmenu through Atmosphere title takeover (hold R while launching a game), then press Y for NetLoader."
echo "Uploading ${NRO} to ${SWITCH_ADDRESS}"
echo "Streaming log to ${LOG_PATH}"
NXLINK_OPTIONS=(--server --retries 30 --address "${SWITCH_ADDRESS}")
if [[ -n "${SWITCH_NRO_ARGS:-}" ]]; then
    NXLINK_OPTIONS+=(--args "${SWITCH_NRO_ARGS}")
fi
if [[ -x /usr/bin/script ]]; then
    # Give nxlink a PTY so its libc stream is line-buffered. Without this, a
    # frozen target can leave the newest diagnostics hidden in a 16 KiB host
    # buffer until the TCP connection finally closes.
    /usr/bin/script -q /dev/null \
        nxlink "${NXLINK_OPTIONS[@]}" "${NRO}" 2>&1 \
        | awk '{ gsub(/\r/, ""); print; fflush(); }' | tee "${LOG_PATH}"
else
    nxlink "${NXLINK_OPTIONS[@]}" "${NRO}" 2>&1 \
        | tee "${LOG_PATH}"
fi

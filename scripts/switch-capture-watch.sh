#!/usr/bin/env bash
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
SWITCH_ADDRESS=${1:-${SWITCH_IP:-}}

if [[ -z "${SWITCH_ADDRESS}" ]]; then
    echo "Usage: $0 <switch-ip>" >&2
    exit 1
fi

LOG_DIR="${REPO_ROOT}/build-switch-logs"
mkdir -p "${LOG_DIR}"
TEMP_PATH="${LOG_DIR}/.manual-screenshot-$$.jpg"

cleanup() {
    rm -f "${TEMP_PATH}"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

echo "R3 screenshot watcher active for ${SWITCH_ADDRESS}"
while true; do
    HTTP_STATUS=$(curl --silent --show-error \
        --connect-timeout 1 --max-time 4 \
        --output "${TEMP_PATH}" --write-out '%{http_code}' \
        "http://${SWITCH_ADDRESS}:47474/manual.jpg" 2>/dev/null || true)

    if [[ "${HTTP_STATUS}" == "200" && -s "${TEMP_PATH}" ]]; then
        TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
        OUTPUT_PATH="${LOG_DIR}/manual-${TIMESTAMP}.jpg"
        SUFFIX=1
        while [[ -e "${OUTPUT_PATH}" ]]; do
            OUTPUT_PATH="${LOG_DIR}/manual-${TIMESTAMP}-${SUFFIX}.jpg"
            SUFFIX=$((SUFFIX + 1))
        done
        mv "${TEMP_PATH}" "${OUTPUT_PATH}"
        echo "R3 screenshot saved: ${OUTPUT_PATH}"
    else
        : > "${TEMP_PATH}"
    fi

    sleep 0.35
done

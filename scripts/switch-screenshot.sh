#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 <switch-ip> [output.jpg]" >&2
    exit 1
fi

SWITCH_ADDRESS=$1
OUTPUT_PATH=${2:-"build-switch-logs/screenshot-$(date '+%Y%m%d-%H%M%S').jpg"}
mkdir -p "$(dirname -- "${OUTPUT_PATH}")"

curl --fail --silent --show-error --max-time 5 \
    "http://${SWITCH_ADDRESS}:47474/screenshot.jpg" \
    --output "${OUTPUT_PATH}"

if [[ ! -s "${OUTPUT_PATH}" ]]; then
    echo "Screenshot response was empty." >&2
    exit 1
fi

echo "Saved screenshot to ${OUTPUT_PATH}"

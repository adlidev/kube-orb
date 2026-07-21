#!/usr/bin/env bash
# Stops the logviewer-dev k3d cluster after TIMEOUT_SECONDS (default 4 hours).
# Run in the background after `make setup` or `make start`:
#   bash infra/reaper.sh &
# The cluster is stopped, not deleted — `make start` brings it back.
# `make teardown` still fully removes it.

set -euo pipefail

CLUSTER="${CLUSTER_NAME:-logviewer-dev}"
TIMEOUT="${TIMEOUT_SECONDS:-14400}"

echo "[reaper] will stop cluster '${CLUSTER}' in ${TIMEOUT}s ($(( TIMEOUT / 3600 ))h)"
sleep "${TIMEOUT}"
echo "[reaper] stopping cluster '${CLUSTER}' ..."
k3d cluster stop "${CLUSTER}"
echo "[reaper] done — run 'make start' to bring it back"

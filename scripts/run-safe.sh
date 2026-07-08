#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

case "${1:-test}" in
  test)
    ./.venv/bin/python -m pytest -q
    ;;
  dev)
    ./.venv/bin/python -m kube_orb
    ;;
  install)
    ./.venv/bin/pip install -e '.[dev]'
    ;;
  infra-build)
    (cd infra && make build)
    ;;
  infra-load)
    (cd infra && make load)
    ;;
  infra-deploy)
    (cd infra && make deploy)
    ;;
  *)
    echo "Usage: $0 {test|dev|install|infra-build|infra-load|infra-deploy}" >&2
    exit 1
    ;;
esac

#!/usr/bin/env bash
# setup.sh — One-shot setup for the k8s-logviewer test infrastructure
# Installs k3d + kubectl (if absent), creates a local cluster, builds
# service images, imports them, and deploys everything.
set -euo pipefail

CLUSTER_NAME="logviewer-dev"
NAMESPACE="logviewer-dev"
SERVICES=(api-gateway auth-service user-service notification-service worker)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}→${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
error() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ─── Prerequisites ────────────────────────────────────────────────────────────
check_docker() {
  if ! command -v docker &>/dev/null; then
    error "Docker is not installed. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ then re-run this script."
  fi
  if ! docker info &>/dev/null; then
    error "Docker daemon is not running. Start Docker Desktop and try again."
  fi
  info "Docker OK"
}

install_k3d() {
  if command -v k3d &>/dev/null; then
    info "k3d already installed ($(k3d version | head -1))"
    return
  fi
  info "Installing k3d ..."
  if command -v brew &>/dev/null; then
    brew install k3d
  else
    curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
  fi
  info "k3d installed"
}

install_kubectl() {
  if command -v kubectl &>/dev/null; then
    info "kubectl already installed ($(kubectl version --client --short 2>/dev/null || kubectl version --client))"
    return
  fi
  info "Installing kubectl ..."
  if command -v brew &>/dev/null; then
    brew install kubectl
  else
    # Linux fallback
    K8S_VER=$(curl -sL https://dl.k8s.io/release/stable.txt)
    curl -sLO "https://dl.k8s.io/release/${K8S_VER}/bin/linux/amd64/kubectl"
    chmod +x kubectl
    sudo mv kubectl /usr/local/bin/kubectl
  fi
  info "kubectl installed"
}

# ─── Cluster ──────────────────────────────────────────────────────────────────
create_cluster() {
  if k3d cluster list | grep -q "^${CLUSTER_NAME}"; then
    warn "Cluster '${CLUSTER_NAME}' already exists — skipping creation."
    warn "Run 'make teardown' first if you want a fresh cluster."
    return
  fi
  info "Creating k3d cluster '${CLUSTER_NAME}' ..."
  k3d cluster create "${CLUSTER_NAME}" \
    --agents 1 \
    --no-lb \
    --wait
  info "Cluster ready"
}

# ─── Images ───────────────────────────────────────────────────────────────────
build_and_load_images() {
  info "Building service images ..."
  for svc in "${SERVICES[@]}"; do
    echo "  Building ${svc} ..."
    docker build -t "${CLUSTER_NAME}/${svc}:latest" \
      "${SCRIPT_DIR}/services/${svc}" \
      --quiet
  done

  info "Importing images into k3d ..."
  for svc in "${SERVICES[@]}"; do
    echo "  Importing ${svc} ..."
    k3d image import "${CLUSTER_NAME}/${svc}:latest" -c "${CLUSTER_NAME}" --verbose 2>&1 \
      | grep -E "(Importing|Successfully)" || true
  done
  info "All images loaded"
}

# ─── Deploy ───────────────────────────────────────────────────────────────────
deploy() {
  info "Applying Kubernetes manifests ..."
  # Namespace must exist before deployments — apply it first
  kubectl apply -f "${SCRIPT_DIR}/k8s/namespace.yaml"
  kubectl apply -f "${SCRIPT_DIR}/k8s/"

  info "Waiting for pods to be ready (timeout 90s) ..."
  for svc in "${SERVICES[@]}"; do
    kubectl rollout status deployment/"${svc}" \
      -n "${NAMESPACE}" \
      --timeout=90s
  done
}

# ─── Summary ─────────────────────────────────────────────────────────────────
print_summary() {
  echo ""
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}  k8s-logviewer test infra is up!${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  kubectl get pods -n "${NAMESPACE}" -o wide
  echo ""
  echo "Useful commands:"
  echo "  make status                        # pod status"
  echo "  make logs                          # tail all services"
  echo "  SERVICE=api-gateway make logs      # tail one service"
  echo "  make teardown                      # remove everything"
  echo ""
}

# ─── Main ─────────────────────────────────────────────────────────────────────
main() {
  echo ""
  echo "Setting up k8s-logviewer test infrastructure ..."
  echo ""
  check_docker
  install_k3d
  install_kubectl
  create_cluster
  build_and_load_images
  deploy
  print_summary
}

main "$@"

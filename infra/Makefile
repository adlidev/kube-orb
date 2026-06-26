CLUSTER_NAME   := logviewer-dev
NAMESPACE      := logviewer-dev
SERVICES       := api-gateway auth-service user-service notification-service worker
SCRIPT_DIR     := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

.PHONY: help setup build load deploy status logs teardown clean

help:
	@echo "k8s-logviewer test infra"
	@echo ""
	@echo "  make setup      Full one-shot setup (install deps, cluster, build, deploy)"
	@echo "  make build      Build all service Docker images"
	@echo "  make load       Import images into k3d cluster"
	@echo "  make deploy     Apply k8s manifests"
	@echo "  make status     Show pod status"
	@echo "  make logs       Tail logs from all services (Ctrl-C to stop)"
	@echo "  make teardown   Delete k3d cluster and all resources"
	@echo "  make clean      Alias for teardown"
	@echo ""
	@echo "  SERVICE=auth-service make logs  # logs for one service"

setup:
	@bash $(SCRIPT_DIR)/setup.sh

build:
	@for svc in $(SERVICES); do \
		echo "→ Building $$svc ..."; \
		docker build -t $(CLUSTER_NAME)/$$svc:latest $(SCRIPT_DIR)/services/$$svc; \
	done

load: build
	@echo "→ Importing images into k3d cluster '$(CLUSTER_NAME)' ..."
	@for svc in $(SERVICES); do \
		k3d image import $(CLUSTER_NAME)/$$svc:latest -c $(CLUSTER_NAME); \
	done

deploy:
	@echo "→ Applying manifests ..."
	@kubectl apply -f $(SCRIPT_DIR)/k8s/namespace.yaml
	@kubectl apply -f $(SCRIPT_DIR)/k8s/
	@echo "→ Waiting for deployments to be ready ..."
	@for svc in $(SERVICES); do \
		kubectl rollout status deployment/$$svc -n $(NAMESPACE) --timeout=60s; \
	done

status:
	@kubectl get pods -n $(NAMESPACE) -o wide

logs:
ifdef SERVICE
	@kubectl logs -n $(NAMESPACE) -l app=$(SERVICE) --all-containers -f --prefix
else
	@kubectl logs -n $(NAMESPACE) --all-containers -f --prefix \
		--selector='app in (api-gateway,auth-service,user-service,notification-service,worker)'
endif

restart:
	@kubectl rollout restart deployment -n $(NAMESPACE)

teardown clean:
	@echo "→ Deleting k3d cluster '$(CLUSTER_NAME)' ..."
	@k3d cluster delete $(CLUSTER_NAME) || true
	@echo "→ Done."

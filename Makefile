# 一鍵開發入口——把 CLAUDE.md 記載的常用指令固化為可重現目標。
# 慣例:所有本機容器/埠用「獨特名 + 高位埠」隔離(CLAUDE.md 鐵則 8),
# 此機同時跑著多個正式服務,勿用預設埠。
#
# 用法:make help
.DEFAULT_GOAL := help

# 可覆寫:本機為 docker-compose(standalone),CI/他環境可 `make COMPOSE="docker compose"`
COMPOSE ?= docker-compose
VENV    ?= .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip

# 本機雲端棧的隔離設定(獨特 project 名 + 高位埠)
COMPOSE_DIR     := cloud/deploy/compose
DEV_PROJECT     ?= drone-dev
export MQTT_PORT     ?= 31883
export PG_PORT       ?= 35432
export GRAFANA_PORT  ?= 33100
export RTSP_PORT     ?= 38554
export PLAYBACK_PORT ?= 39996
export MTX_API_PORT  ?= 39997
export LOGSVC_PORT   ?= 38090

.PHONY: help venv install lint fmt fmt-check test proto dev dev-down dev-logs sitl clean

help: ## 顯示可用目標
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## 建立 Python 3.10+ 虛擬環境
	python3 -m venv $(VENV)

install: venv ## 安裝所有子系統依賴(對齊 ci.yml)
	$(PIP) install -q -U pip ruff pytest pytest-cov mypy
	@for f in tools/requirements.txt \
	          tools/sitl_scenarios/requirements.txt \
	          onboard/drone_agent/requirements.txt \
	          cloud/ingest/requirements.txt \
	          cloud/log_svc/requirements.txt; do \
		if [ -f "$$f" ]; then echo "pip install -r $$f"; $(PIP) install -q -r "$$f"; fi; \
	done
	@if [ -d interfaces/proto/gen/python ]; then $(PIP) install -q -e interfaces/proto/gen/python; fi
	@if [ -f onboard/mission_exec/pyproject.toml ]; then $(PIP) install -q -e onboard/mission_exec; fi
	@echo "✓ 依賴安裝完成"

lint: ## ruff 靜態檢查
	$(VENV)/bin/ruff check .

fmt: ## ruff 自動格式化
	$(VENV)/bin/ruff format .

fmt-check: ## ruff 格式檢查(不改檔)
	$(VENV)/bin/ruff format --check .

test: ## 全部單元測試(不需 SITL/docker)
	$(PY) -m pytest -q

proto: ## 重新生成 protobuf 程式碼(改 .proto 後必跑)
	cd interfaces/proto && ./generate.sh

dev: ## 起本機雲端棧(隔離高位埠;結束用 make dev-down)
	cd $(COMPOSE_DIR) && $(COMPOSE) -p $(DEV_PROJECT) up -d --build --wait
	@echo "✓ 雲端棧已起:Grafana http://localhost:$(GRAFANA_PORT) · MQTT :$(MQTT_PORT) · PG :$(PG_PORT)"
	@echo "  灌假遙測:$(PY) tools/publish_fake_telemetry.py --mqtt-port $(MQTT_PORT) --count 10"

dev-down: ## 停本機雲端棧並清 volume
	cd $(COMPOSE_DIR) && $(COMPOSE) -p $(DEV_PROJECT) down -v

dev-logs: ## 追本機雲端棧日誌
	cd $(COMPOSE_DIR) && $(COMPOSE) -p $(DEV_PROJECT) logs -f

sitl: ## 起 headless PX4 SITL 容器(勿做 -p 埠映射,見 CLAUDE.md 鐵則 1)
	docker run --rm -d --name drone-sitl-dev jonasvautherin/px4-gazebo-headless:1.15.4
	@echo "✓ SITL 啟動中(等 ~40-60s GPS lock);客戶端 udpin://0.0.0.0:14540;停:docker stop drone-sitl-dev"

clean: ## 清除虛擬環境與快取
	rm -rf $(VENV) .pytest_cache
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} + 2>/dev/null || true

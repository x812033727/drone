# firmware 一鍵入口(對齊根 Makefile 慣例;細節見 firmware/README.md)。
# 用法:make -C firmware help
.DEFAULT_GOAL := help

# PX4 原始碼位置(gitignored;CI 與本機共用此預設)
export PX4_SRC ?= $(CURDIR)/.px4
VENV ?= $(CURDIR)/.venv-px4
PIP  := $(VENV)/bin/pip

.PHONY: help fetch deps patch build smoke all clean

help: ## 顯示可用目標
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

fetch: ## 抓 PX4 upstream(釘版於 px4.lock,冪等)
	bash tools/fetch_px4.sh

deps: ## 建置用 python 依賴(釘版,裝進 firmware/.venv-px4)
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install -q -r tools/requirements-px4-build.txt

patch: fetch ## 套用 patches/*.patch(git apply --3way,冪等)
	bash tools/apply_patches.sh

build: patch ## 建置 px4_sitl_default(啟用 ccache 若可用)
	. $(VENV)/bin/activate && $(MAKE) -C $(PX4_SRC) px4_sitl_default

smoke: ## SIH 起機 + heartbeat 煙霧(需先 build)
	. $(VENV)/bin/activate && bash tools/run_sitl_smoke.sh

all: deps build smoke ## fetch→deps→patch→build→smoke 全流程

clean: ## 移除 PX4 原始碼與 venv(ccache 保留)
	rm -rf $(PX4_SRC) $(VENV)

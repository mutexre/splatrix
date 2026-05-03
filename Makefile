# Splatrix per-worktree task runner.
#
# Uniform interface usable inside any worktree, with or without conda env active.
# All Python invocations go through `conda run -n splatrix --no-capture-output`
# so targets work whether or not the env is currently activated.

CONDA_ENV       ?= splatrix
PYTHON          := conda run -n $(CONDA_ENV) --no-capture-output python
PIP             := conda run -n $(CONDA_ENV) --no-capture-output pip
PYTEST          := conda run -n $(CONDA_ENV) --no-capture-output pytest

SERVER_LOG_DIR  := $(HOME)/.splatrix/logs
SERVER_LOG      := $(SERVER_LOG_DIR)/server-dev.log

.PHONY: help app server run test install clean

help:
	@printf "Splatrix Makefile targets:\n\n"
	@printf "  make run       Start server (background) + GUI app (foreground).\n"
	@printf "                 Server is killed when the app exits.\n"
	@printf "  make app       Start GUI app only (foreground). Assumes server is already running.\n"
	@printf "  make server    Start processing server only (foreground).\n"
	@printf "  make test      Run pytest.\n"
	@printf "  make install   pip install -e .[dev] inside the conda env.\n"
	@printf "  make clean     Remove build artefacts and Python caches.\n"
	@printf "  make help      Show this message.\n"
	@printf "\nConda env: %s\n" "$(CONDA_ENV)"

app:
	@$(PYTHON) run.py

server:
	@$(PYTHON) -m splatrix.server

run:
	@mkdir -p "$(SERVER_LOG_DIR)"
	@printf "[run] starting server (log: %s)\n" "$(SERVER_LOG)"
	@$(PYTHON) -m splatrix.server >>"$(SERVER_LOG)" 2>&1 & \
		SERVER_PID=$$!; \
		trap 'printf "\n[run] stopping server (pid %s)\n" "$$SERVER_PID"; kill $$SERVER_PID 2>/dev/null; wait $$SERVER_PID 2>/dev/null; exit' INT TERM EXIT; \
		sleep 0.5; \
		printf "[run] server pid %s, starting app...\n" "$$SERVER_PID"; \
		$(PYTHON) run.py; \
		APP_EXIT=$$?; \
		printf "[run] app exited (%s), shutting down server...\n" "$$APP_EXIT"; \
		kill $$SERVER_PID 2>/dev/null; \
		wait $$SERVER_PID 2>/dev/null; \
		exit $$APP_EXIT

test:
	@$(PYTEST)

install:
	@$(PIP) install -e ".[dev]"

clean:
	@find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
	@rm -rf build dist .pytest_cache .ruff_cache
	@printf "[clean] done\n"

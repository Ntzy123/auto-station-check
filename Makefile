# ============================================================================
# Makefile - auto_station_check
# Cross-platform (Windows / Linux / macOS)
# ============================================================================

# --- OS detection ---
ifeq ($(OS),Windows_NT)
    PYTHON      = python
    VENV_PYTHON = .venv\Scripts\python.exe
    VENV_PIP    = .venv\Scripts\pip.exe
    SEP         = ;
    NULL        = nul
else
    PYTHON      = python3
    VENV_PYTHON = .venv/bin/python
    VENV_PIP    = .venv/bin/pip
    SEP         = :
    NULL        = /dev/null
endif

APP_NAME = auto_station_check
ICON     = res/auto-station-check.ico

.PHONY: help setup mirror run test build

# --- File target: only creates venv when the Python interpreter is missing ---
$(VENV_PYTHON):
	$(PYTHON) -m venv .venv

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "  setup    Create venv and install dependencies"
	@echo "  mirror   Switch pip to Tsinghua mirror"
	@echo "  run      Run the application via python -m"
	@echo "  test     Run tests with pytest"
	@echo "  build    Package with PyInstaller (timestamped name)"
	@echo "  help     Show this help"

setup: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install --upgrade pip > $(NULL) 2>&1
	$(VENV_PIP) install -e .
	@$(PYTHON) setup_deps.py
	$(VENV_PIP) install -e ../easycheck_manager
	@echo "Setup complete."

mirror: $(VENV_PYTHON)
	$(VENV_PIP) config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
	@echo "Mirror set."

run: $(VENV_PYTHON)
	$(VENV_PYTHON) -m $(APP_NAME)

test: $(VENV_PYTHON)
	$(VENV_PIP) install pytest pytest-cov 2>&1
	$(VENV_PYTHON) -m pytest tests/ -v --cov=src/$(APP_NAME) --cov-report=term-missing

build: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install --upgrade pip > $(NULL) 2>&1
	$(VENV_PIP) install -e .
	$(VENV_PYTHON) -m PyInstaller --onefile --name=$(APP_NAME)_$(shell $(PYTHON) -c "import datetime;print(datetime.datetime.now().strftime('%Y%m%d%H%M%S'))") --icon=$(ICON) --hidden-import=selenium.webdriver.edge.webdriver --hidden-import=selenium.webdriver.edge.service --hidden-import=selenium.webdriver.edge.options --hidden-import=selenium.webdriver.common.by --hidden-import=selenium.webdriver.common.keys --hidden-import=selenium.webdriver.remote.remote_connection --hidden-import=selenium.webdriver.support.ui --hidden-import=selenium.webdriver.support.expected_conditions --hidden-import=selenium.common.exceptions -c src/$(APP_NAME)/__main__.py
	@echo "Build complete: dist/"

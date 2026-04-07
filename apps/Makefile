.PHONY: all clean dist help ecg_viewer esp_logger movesense_logger multi_movesense

APPS := ecg_viewer esp_logger movesense_logger multi_movesense
DIST_DIR := dist
BUILD_DIR := build

# Detect OS for cross-platform compatibility
ifeq ($(OS),Windows_NT)
    DETECTED_OS := Windows
    RM := cmd /C del /F /Q
    RMDIR := cmd /C rmdir /S /Q
    MKDIR := cmd /C if not exist
    COPY := cmd /C copy /Y
    NPROC := $(NUMBER_OF_PROCESSORS)
else
    DETECTED_OS := $(shell uname -s)
    RM := rm -f
    RMDIR := rm -rf
    MKDIR := mkdir -p
    COPY := cp
    NPROC := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
endif

# Enable parallel builds by default using all available cores
MAKEFLAGS += -j$(NPROC)

# Default target
all: $(APPS)

# Individual app targets
ecg_viewer:
	@echo "Building iFCH ECG Viewer..."
	cd ecg_viewer && uv run pyinstaller --onefile --windowed --name iFCH_ECG_Viewer main.py
	@echo "✓ iFCH ECG Viewer built"

esp_logger:
	@echo "Building iFCH ESP Logger..."
	cd esp_logger && uv run pyinstaller --onefile --windowed --name iFCH_ESP_Logger_Control main.py
	@echo "✓ iFCH ESP Logger built"

movesense_logger:
	@echo "Building iFCH Movesense Logger..."
	cd movesense_logger && uv run pyinstaller --onefile --windowed --name iFCH_Movesense_Logger main.py
	@echo "✓ iFCH Movesense Logger built"

multi_movesense:
	@echo "Building iFCH Multi Movesense..."
	cd multi_movesense && uv run pyinstaller --onefile --windowed --name iFCH_Multi_Movesense main.py
	@echo "✓ iFCH Multi Movesense built"

# Collect all built binaries to a central dist folder
dist: all
	@echo "Collecting binaries to $(DIST_DIR)..."
ifeq ($(OS),Windows_NT)
	@$(MKDIR) "$(DIST_DIR)" $(MKDIR) "$(DIST_DIR)"
	@for %%a in ($(APPS)) do @( \
		if exist %%a\dist\*.exe ( \
			echo   Copying %%a binaries... & \
			$(COPY) %%a\dist\*.exe $(DIST_DIR)\ >nul \
		) \
	)
else
	@mkdir -p $(DIST_DIR)
	@for app in $(APPS); do \
		if [ -d $$app/dist ]; then \
			if ls $$app/dist/*.exe 1>/dev/null 2>&1; then \
				echo "  Copying $$app binaries..."; \
				cp $$app/dist/*.exe $(DIST_DIR)/; \
			elif ls $$app/dist/* 1>/dev/null 2>&1; then \
				echo "  Copying $$app binaries..."; \
				cp $$app/dist/* $(DIST_DIR)/; \
			fi; \
		fi; \
	done
endif
	@echo "✓ All binaries collected to $(DIST_DIR)/"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
ifeq ($(OS),Windows_NT)
	@for %%a in ($(APPS)) do @( \
		if exist %%a\dist $(RMDIR) %%a\dist 2>nul & \
		if exist %%a\build $(RMDIR) %%a\build 2>nul & \
		if exist %%a\*.spec del /F /Q %%a\*.spec 2>nul \
	)
else
	@for app in $(APPS); do \
		if [ -d $$app/dist ]; then rm -rf $$app/dist; fi; \
		if [ -d $$app/build ]; then rm -rf $$app/build; fi; \
		if [ -f $$app/*.spec ]; then rm -f $$app/*.spec; fi; \
	done
endif
	@echo "✓ Cleaned"

# Clean everything including central dist folder
clean-all: clean
	@echo "Removing central dist directory..."
ifeq ($(OS),Windows_NT)
	@if exist $(DIST_DIR) $(RMDIR) $(DIST_DIR) 2>nul
else
	@rm -rf $(DIST_DIR)
endif
	@echo "✓ Fully cleaned"

# Help target
help:
	@echo "iFCH Apps Build System"
	@echo ""
	@echo "Targets:"
	@echo "  make all              - Build all applications"
	@echo "  make ecg_viewer       - Build ECG Viewer only"
	@echo "  make esp_logger       - Build ESP Logger only"
	@echo "  make movesense_logger - Build Movesense Logger only"
	@echo "  make multi_movesense  - Build Multi Movesense only"
	@echo "  make dist             - Build all and collect to dist/ folder"
	@echo "  make clean            - Remove build artifacts from each app"
	@echo "  make clean-all        - Remove all build artifacts and dist folder"
	@echo "  make help             - Show this help message"

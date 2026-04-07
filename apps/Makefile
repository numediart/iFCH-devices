.PHONY: all clean dist help ecg_viewer esp_logger movesense_logger multi_movesense

APPS := ecg_viewer esp_logger movesense_logger multi_movesense
DIST_DIR := dist
BUILD_DIR := build

# Enable parallel builds by default using all available cores
MAKEFLAGS += -j$(shell nproc)

# Default target
all: $(APPS)

# Individual app targets
ecg_viewer:
	@echo "Building iFCH ECG Viewer..."
	cd ecg_viewer && uv run pyinstaller --onefile --windowed --name iFCH_ECG_viewer main.py
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
	@mkdir -p $(DIST_DIR)
	@for app in $(APPS); do \
		if [ -f $$app/dist/iFCH_$$app ]; then \
			echo "  Copying $$app binary..."; \
			cp $$app/dist/iFCH_$$app $(DIST_DIR)/; \
		elif [ -f $$app/dist/iFCH_$${app}.exe ]; then \
			echo "  Copying $$app binary..."; \
			cp $$app/dist/iFCH_$${app}.exe $(DIST_DIR)/; \
		fi \
	done
	@echo "✓ All binaries collected to $(DIST_DIR)/"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@for app in $(APPS); do \
		if [ -d $$app/dist ]; then rm -rf $$app/dist; fi; \
		if [ -d $$app/build ]; then rm -rf $$app/build; fi; \
		if [ -f $$app/*.spec ]; then rm -f $$app/*.spec; fi; \
	done
	@echo "✓ Cleaned"

# Clean everything including central dist folder
clean-all: clean
	@echo "Removing central dist directory..."
	@rm -rf $(DIST_DIR)
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

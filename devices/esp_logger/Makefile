SHELL := /bin/bash
IDF_ACTIVATE := ./env.sh
IDF_PY := python "$$IDF_PATH/tools/idf.py"
IDF_CMD := source "$(IDF_ACTIVATE)" && $(IDF_PY)
.DEFAULT_GOAL := help
.PHONY: clean build flash

clean:
	$(IDF_CMD) fullclean

build:
	$(IDF_CMD) build

flash:
	$(IDF_CMD) build flash

help:
	@echo "Usage:"
	@echo "  make help        # Show this help message"
	@echo "  make build       # Build the binary"
	@echo "  make flash       # Build and flash the device"
	@echo "  make clean       # Clean build directory"
ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
build ?= Release
device ?= SS2_NAND
BUILD_DIR:=${ROOT_DIR}/build_${device}_${build}

.DEFAULT_GOAL := help

dist: compile
	docker run --rm -w /movesense/build_${device}_${build}/ -v ${ROOT_DIR}:/movesense:delegated movesense/sensor-build-env:2.2 ninja dfupkg


compile: config
	docker run --rm -w /movesense/build_${device}_${build}/ -v ${ROOT_DIR}:/movesense:delegated movesense/sensor-build-env:2.2 ninja

	
config:
	mkdir -p ${BUILD_DIR}/

	docker run --rm -w /movesense/build_${device}_${build}/ -v ${ROOT_DIR}:/movesense:delegated movesense/sensor-build-env:2.2 cmake -G "Ninja" -DCMAKE_TOOLCHAIN_FILE=../movesense-device-lib/MovesenseCoreLib/toolchain/gcc-nrf52.cmake -DMOVESENSE_CORE_LIBRARY=../movesense-device-lib/MovesenseCoreLib ../ -DCMAKE_BUILD_TYPE=${build} -DHWCONFIG=${device} ../src


clean:
	docker run --rm -w /movesense -v ${ROOT_DIR}:/movesense:delegated movesense/sensor-build-env:2.2 rm -rf build_*/


help:
	@echo "Usage:"
	@echo "  make help                                  # Show this help message"
	@echo "  make dist build=Release device=SS2_NAND    # Build and create DFU package"
	@echo "      build can be Release or Debug (default: Release)"
	@echo "      device can be SS2 or SS2_NAND (default: SS2_NAND)"
	@echo "  make clean                                 # Clean build directory"
	
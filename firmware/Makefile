ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
name = iFCH_gatt
build = Release

compile: config
	docker run --rm -w /movesense/build/ -v ${ROOT_DIR}:/movesense:delegated movesense/sensor-build-env:2.2 ninja


dist: compile
	docker run --rm -w /movesense/build/ -v ${ROOT_DIR}:/movesense:delegated movesense/sensor-build-env:2.2 ninja dfupkg

	
config:
	mkdir -p ${ROOT_DIR}/build/

	docker run --rm -w /movesense/build/ -v ${ROOT_DIR}:/movesense:delegated movesense/sensor-build-env:2.2 cmake -G "Ninja" -DCMAKE_TOOLCHAIN_FILE=../movesense-device-lib/MovesenseCoreLib/toolchain/gcc-nrf52.cmake -DMOVESENSE_CORE_LIBRARY=../movesense-device-lib/MovesenseCoreLib ../ -DCMAKE_BUILD_TYPE=$(build) -DHWCONFIG=SS2_NAND ../$(name)


clean:
	docker run --rm -w /movesense -v ${ROOT_DIR}:/movesense:delegated movesense/sensor-build-env:2.2 rm -rf build/

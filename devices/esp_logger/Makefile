IDF_ACTIVATE := ./env.sh
.DEFAULT_GOAL := build
.PHONY: clean build flash

clean:
	source "$(IDF_ACTIVATE)" && idf.py fullclean

build:
	source "$(IDF_ACTIVATE)" && idf.py build

flash:
	source "$(IDF_ACTIVATE)" && idf.py build flash
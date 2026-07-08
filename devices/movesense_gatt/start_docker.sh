#!/bin/bash

# Start an interactive Movesense build container mounted to this project directory.

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
docker run -it --rm -w /movesense -v $SCRIPT_DIR:/movesense:Z movesense/sensor-build-env:2.2


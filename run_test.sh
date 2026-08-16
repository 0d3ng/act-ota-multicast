#!/bin/bash
set -a
source .env.test
set +a

mkdir -p build
if [ ! -f build/firmware-ota-rolling-key.bin ]; then
  head -c 1024 /dev/urandom > build/firmware-ota-rolling-key.bin
fi

python3 main.py

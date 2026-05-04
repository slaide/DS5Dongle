#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

IMAGE=ds5dongle-builder

docker build -t "$IMAGE" .

git submodule update --init --recursive

docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "$PWD":/work \
    "$IMAGE" \
    bash -c '
        set -euo pipefail
        cmake -S . -B build -G Ninja -DPICO_BOARD=pico2_w
        cmake --build build -j"$(nproc)"
    '

echo
echo "Firmware: $PWD/build/ds5-bridge.uf2"
ls -lh build/ds5-bridge.uf2

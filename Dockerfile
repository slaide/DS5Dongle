FROM debian:trixie-slim

ARG PICO_SDK_VERSION=2.2.0

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ninja-build \
        git \
        python3 \
        ca-certificates \
        gcc-arm-none-eabi \
        libnewlib-arm-none-eabi \
        libstdc++-arm-none-eabi-newlib \
    && rm -rf /var/lib/apt/lists/*

ENV PICO_SDK_PATH=/opt/pico-sdk
RUN git clone --depth 1 -b ${PICO_SDK_VERSION} \
        https://github.com/raspberrypi/pico-sdk.git ${PICO_SDK_PATH} \
 && git -C ${PICO_SDK_PATH} submodule update --init --recursive --depth 1

# The project requires a newer TinyUSB than the one pinned by pico-sdk 2.2.0
# (uses the 4-arg TUD_AUDIO_EP_SIZE and AUDIO10_* enums). Pinned to the master
# tip from 2026-05-04 for reproducibility.
ARG TINYUSB_COMMIT=3170fa0bf2667c4cc8e5a22944c15686c681654e
RUN cd ${PICO_SDK_PATH}/lib/tinyusb \
 && git fetch --depth 1 origin ${TINYUSB_COMMIT} \
 && git checkout ${TINYUSB_COMMIT}

RUN chmod -R a+rX ${PICO_SDK_PATH}

WORKDIR /work

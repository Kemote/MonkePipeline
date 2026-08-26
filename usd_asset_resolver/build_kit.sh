#!/bin/bash

# Builds monke_resolver for use inside Omniverse Kit (kit-app-template).
#
# Kit bundles its own USD 0.25.11 build (via the omni.usd.libs extension) and
# does NOT ship USD headers or CMake package config. So here we:
#   1. Use headers/CMake config from a headless OpenUSD 0.25.11 source build
#      (built from the same v25.11 tag Kit ships) purely to compile against
#      the right pxr/usd/ar API.
#   2. Link the plugin directly against Kit's own libusd_ar.so instead of the
#      library our headless build produced, so at runtime the plugin shares
#      the exact USD binary already loaded by Kit rather than pulling in a
#      second, separately-built copy (which would duplicate TfType
#      registrations and crash the app).

set -e

PROJECT_DIR="/home/kemot/Documents/Dev/MonkePipeline/usd_asset_resolver"
PROJECT_BUILD_DIR="${PROJECT_DIR}/build_kit"
USD_HEADERS_DIR="/home/kemot/UsdRoot_25_11"
KIT_APP_TEMPLATE_DIR="/home/kemot/kit-app-template"

# Kit's omni.usd.libs extension folder name is pinned to the kit-sdk version
# via kit-sdk.packman.xml, but the actual content lives behind a
# content-addressed symlink - so resolve it by globbing extscache instead of
# hardcoding the hash.
KIT_USD_LIBS_EXT_DIR=$(find "${KIT_APP_TEMPLATE_DIR}/_build/linux-x86_64/release/extscache" \
    -maxdepth 1 -iname "omni.usd.libs-*" | head -n 1)

if [ -z "$KIT_USD_LIBS_EXT_DIR" ]; then
    echo "ERROR: could not find omni.usd.libs extension under ${KIT_APP_TEMPLATE_DIR}/_build/linux-x86_64/release/extscache" >&2
    echo "Has the Kit app been pulled/built at least once (./repo.sh build)?" >&2
    exit 1
fi

KIT_USD_LIBS_DIR="${KIT_USD_LIBS_EXT_DIR}/bin"

if [ ! -f "${KIT_USD_LIBS_DIR}/libusd_ar.so" ]; then
    echo "ERROR: libusd_ar.so not found at ${KIT_USD_LIBS_DIR}" >&2
    exit 1
fi

if [ ! -d "$USD_HEADERS_DIR" ]; then
    echo "ERROR: ${USD_HEADERS_DIR} not found - build headless OpenUSD 0.25.11 first" >&2
    echo "  cd /home/kemot/OpenUSD-src-25.11 && python3 build_scripts/build_usd.py --no-imaging --no-usdview --no-examples --no-tutorials --no-tests ${USD_HEADERS_DIR}" >&2
    exit 1
fi

echo "Using USD headers from: ${USD_HEADERS_DIR}"
echo "Linking against Kit's runtime libs from: ${KIT_USD_LIBS_DIR}"

(
    mkdir -p "$PROJECT_BUILD_DIR"
    cd "$PROJECT_BUILD_DIR"
    cmake "$PROJECT_DIR" \
      -Dpxr_DIR="${USD_HEADERS_DIR}" \
      -DCMAKE_PREFIX_PATH="${USD_HEADERS_DIR}" \
      -DBUILD_FOR_KIT=ON \
      -DKIT_USD_LIBS_DIR="${KIT_USD_LIBS_DIR}"

    cmake --build . --config Release
)

echo "--- MonkeMonke for Kit!! Waaghhh!! ---"

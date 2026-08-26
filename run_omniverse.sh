#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/pipeline.env"
[ -f "$ENV_FILE" ] || ENV_FILE="$SCRIPT_DIR/pipeline.env"
set -a
source "$ENV_FILE"
set +a

PXR_PLUGINPATH_NAME=$PXR_PLUGINPATH_NAME_OMNIVERSE \
$OMNIVERSE_KIT_LAUNCHER launch $OMNIVERSE_KIT_APP

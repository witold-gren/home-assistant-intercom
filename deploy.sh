#!/bin/sh
# Development helper: copy the integration to /config/custom_components on a mounted Samba share
# (without HACS). Override the mount point with CONFIG=/path ./deploy.sh.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${CONFIG:-/Volumes/config}"
[ -d "$CONFIG/custom_components" ] || { echo "Mount the Home Assistant config share at $CONFIG first"; exit 1; }
# SMB: --inplace, because writing a temp file and renaming it is sometimes rejected
rsync -a --inplace --delete --exclude '__pycache__' --exclude '.DS_Store' \
    "$HERE/custom_components/intercom/" "$CONFIG/custom_components/intercom/"
echo "Deployed integration $(grep '"version"' "$HERE/custom_components/intercom/manifest.json" | tr -d ' ,'); restart Home Assistant"

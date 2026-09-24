#!/usr/bin/env bash
# Universal DAIO v2.1 Installer
set -euo pipefail

TARGET_DIR="${1:-.}"
echo "📦 Installing DAIO v2.1 Closed Loop into: ${TARGET_DIR}..."

mkdir -p "${TARGET_DIR}/_daio"

# Determine script root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Copy executable wrapper
cp "${SCRIPT_DIR}/daio" "${TARGET_DIR}/daio"
chmod +x "${TARGET_DIR}/daio"

# Copy internal scripts for standalone portability
mkdir -p "${TARGET_DIR}/_daio/scripts"
cp -r "${SCRIPT_DIR}/scripts/"* "${TARGET_DIR}/_daio/scripts/"

# Copy default config if none exists
if [ ! -f "${TARGET_DIR}/_daio/daio_config.json" ]; then
    cp "${SCRIPT_DIR}/daio_config.example.json" "${TARGET_DIR}/_daio/daio_config.json"
    echo "📄 Created template configuration: _daio/daio_config.json"
fi

echo "✨ DAIO v2.1 successfully installed! Run './daio start' to begin autonomous orchestration."


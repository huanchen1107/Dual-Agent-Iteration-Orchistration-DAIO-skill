#!/usr/bin/env bash
# Universal DAIO v2.1 Installer & Skill Synchronizer
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMIT_SHA="$(git -C "${SCRIPT_DIR}" rev-parse HEAD 2>/dev/null || echo "UNKNOWN")"
NOW_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

if [ "${1:-}" = "--skill" ]; then
    SKILL_DIR="${HOME}/.gemini/config/skills/daio"
    echo "📦 Synchronizing DAIO Skill into: ${SKILL_DIR}..."
    mkdir -p "${SKILL_DIR}/scripts" "${SKILL_DIR}/tests" "${SKILL_DIR}/cloudflare"

    # Copy files
    cp "${SCRIPT_DIR}/SKILL.md" "${SKILL_DIR}/SKILL.md"
    cp "${SCRIPT_DIR}/README.md" "${SKILL_DIR}/README.md"
    cp "${SCRIPT_DIR}/daio" "${SKILL_DIR}/daio"
    chmod +x "${SKILL_DIR}/daio"
    cp "${SCRIPT_DIR}/install.sh" "${SKILL_DIR}/install.sh"
    chmod +x "${SKILL_DIR}/install.sh"
    cp "${SCRIPT_DIR}/pytest.ini" "${SKILL_DIR}/pytest.ini"
    cp "${SCRIPT_DIR}/daio_config.example.json" "${SKILL_DIR}/daio_config.example.json"

    # Copy scripts
    cp -r "${SCRIPT_DIR}/scripts/"* "${SKILL_DIR}/scripts/"

    # Copy tests
    cp -r "${SCRIPT_DIR}/tests/"* "${SKILL_DIR}/tests/"

    # Copy cloudflare
    cp -r "${SCRIPT_DIR}/cloudflare/"* "${SKILL_DIR}/cloudflare/"

    # Generate PROVENANCE.json
    cat <<EOF > "${SKILL_DIR}/PROVENANCE.json"
{
  "skill_name": "daio",
  "skill_version": "2.1.0",
  "source_repository": "https://github.com/huanchen1107/Dual-Agent-Iteration-Orchistration-DAIO-skill.git",
  "source_commit_sha": "${COMMIT_SHA}",
  "installed_at": "${NOW_ISO}",
  "protocols": [
    "daio-rpc/v1",
    "rpc-2.v1"
  ],
  "capabilities": [
    "RPC-1 Status Plane",
    "RPC-2A Remote Decision Transport",
    "RPC-2B Atomic Compare-and-Apply Store",
    "Singleton Supervisor",
    "Handoff Watchdog",
    "CDP Bridge",
    "Workspace Scope Guardrail"
  ]
}
EOF
    echo "✨ DAIO Skill successfully synchronized to ${SKILL_DIR} (Commit: ${COMMIT_SHA})"
    exit 0
fi

TARGET_DIR="${1:-.}"
echo "📦 Installing DAIO v2.1 Closed Loop into: ${TARGET_DIR}..."

mkdir -p "${TARGET_DIR}/_daio/scripts" "${TARGET_DIR}/_daio/cloudflare"

# Copy executable wrapper
cp "${SCRIPT_DIR}/daio" "${TARGET_DIR}/daio"
chmod +x "${TARGET_DIR}/daio"

# Copy internal scripts for standalone portability
cp -r "${SCRIPT_DIR}/scripts/"* "${TARGET_DIR}/_daio/scripts/"

# Copy cloudflare templates
cp -r "${SCRIPT_DIR}/cloudflare/"* "${TARGET_DIR}/_daio/cloudflare/"

# Copy default config if none exists
if [ ! -f "${TARGET_DIR}/_daio/daio_config.json" ]; then
    cp "${SCRIPT_DIR}/daio_config.example.json" "${TARGET_DIR}/_daio/daio_config.json"
    echo "📄 Created template configuration: _daio/daio_config.json"
fi

# Write PROVENANCE.json
cat <<EOF > "${TARGET_DIR}/_daio/PROVENANCE.json"
{
  "skill_name": "daio",
  "skill_version": "2.1.0",
  "source_repository": "https://github.com/huanchen1107/Dual-Agent-Iteration-Orchistration-DAIO-skill.git",
  "source_commit_sha": "${COMMIT_SHA}",
  "installed_at": "${NOW_ISO}",
  "protocols": ["daio-rpc/v1", "rpc-2.v1"]
}
EOF

echo "✨ DAIO v2.1 successfully installed in ${TARGET_DIR}! (Source SHA: ${COMMIT_SHA})"

"""
Provider-Neutral Capability Discovery & Login-First CLI Inspector (daio-agent/v1 / Phase B3).
Safely detects installed CLI tools, authentication modes, and advertised capabilities without credentials exposure.
"""

from __future__ import annotations
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Set

from .agent_contract import (
    AgentCapability,
    AgentRole,
    AuthMode,
    AuthStatus,
    AvailabilityStatus,
    InstallationStatus,
    ProviderDescriptor,
    ProviderState,
    ProviderTransport,
)

logger = logging.getLogger("DAIO_CLI_Discovery")


class CLIProviderDiscovery:
    """
    Non-destructive system inspector that discovers CLI providers, validates executables,
    extracts versions, and determines capability and login-session availability.
    """

    KNOWN_CLI_SPECS: Dict[str, Dict[str, Any]] = {
        "antigravity": {
            "display_name": "Antigravity CLI (agy)",
            "exec_names": ["agy", "antigravity"],
            "fallback_paths": [str(Path.home() / ".local" / "bin" / "agy")],
            "auth_mode": AuthMode.LOGIN_SESSION,
            "session_markers": [str(Path.home() / ".gemini"), str(Path.home() / ".antigravity")],
            "capabilities": {
                AgentCapability.READ_REPOSITORY,
                AgentCapability.WRITE_REPOSITORY,
                AgentCapability.PROPOSE_EDITS,
                AgentCapability.RUN_COMMANDS,
                AgentCapability.RUN_TESTS,
                AgentCapability.GIT_COMMIT,
                AgentCapability.ARTIFACT_GENERATION,
                AgentCapability.STRUCTURED_DECISION,
            },
            "supported_roles": {
                AgentRole.ENGINEERING_EXECUTION,
                AgentRole.LEAD_ARCHITECT,
                AgentRole.REVIEW_AGENT,
                AgentRole.TEST_AGENT,
            },
            "supports_non_interactive": True,
            "supports_structured_output": True,
            "supports_sandbox": True,
            "supports_unattended": True,
        },
        "gemini_cli": {
            "display_name": "Gemini CLI",
            "exec_names": ["gemini"],
            "fallback_paths": [
                "/opt/homebrew/bin/gemini",
                "/usr/local/bin/gemini",
                str(Path.home() / ".local" / "bin" / "gemini")
            ],
            "auth_mode": AuthMode.LOGIN_SESSION,
            "session_markers": [str(Path.home() / ".gemini"), str(Path.home() / ".config" / "gemini")],
            "capabilities": {
                AgentCapability.READ_REPOSITORY,
                AgentCapability.PROPOSE_EDITS,
                AgentCapability.ARCHITECT_REVIEW,
                AgentCapability.STRUCTURED_DECISION,
                AgentCapability.ARTIFACT_GENERATION,
            },
            "supported_roles": {
                AgentRole.LEAD_ARCHITECT,
                AgentRole.ENGINEERING_EXECUTION,
                AgentRole.REVIEW_AGENT,
            },
            "supports_non_interactive": True,
            "supports_structured_output": True,
            "supports_sandbox": True,
            "supports_unattended": True,
        },
        "codex_cli": {
            "display_name": "Codex CLI",
            "exec_names": ["codex"],
            "fallback_paths": [
                "/opt/homebrew/bin/codex",
                "/usr/local/bin/codex",
                str(Path.home() / ".local" / "bin" / "codex")
            ],
            "auth_mode": AuthMode.LOGIN_SESSION,
            "session_markers": [str(Path.home() / ".codex"), str(Path.home() / ".config" / "codex")],
            "capabilities": {
                AgentCapability.READ_REPOSITORY,
                AgentCapability.PROPOSE_EDITS,
                AgentCapability.RUN_COMMANDS,
                AgentCapability.RUN_TESTS,
                AgentCapability.ARTIFACT_GENERATION,
            },
            "supported_roles": {
                AgentRole.ENGINEERING_EXECUTION,
                AgentRole.TEST_AGENT,
            },
            "supports_non_interactive": True,
            "supports_structured_output": True,
            "supports_sandbox": True,
            "supports_unattended": True,
        },
        "opencode_cli": {
            "display_name": "OpenCode CLI",
            "exec_names": ["opencode"],
            "fallback_paths": [
                str(Path.home() / ".opencode" / "bin" / "opencode"),
                "/opt/homebrew/bin/opencode",
                str(Path.home() / ".local" / "bin" / "opencode")
            ],
            "auth_mode": AuthMode.PROVIDER_DEPENDENT,
            "session_markers": [str(Path.home() / ".opencode"), str(Path.home() / ".config" / "opencode")],
            "capabilities": {
                AgentCapability.READ_REPOSITORY,
                AgentCapability.PROPOSE_EDITS,
                AgentCapability.RUN_COMMANDS,
                AgentCapability.RUN_TESTS,
                AgentCapability.ARTIFACT_GENERATION,
            },
            "supported_roles": {
                AgentRole.ENGINEERING_EXECUTION,
                AgentRole.TEST_AGENT,
            },
            "supports_non_interactive": True,
            "supports_structured_output": True,
            "supports_sandbox": True,
            "supports_unattended": True,
        },
        "claude_code": {
            "display_name": "Claude Code CLI",
            "exec_names": ["claude"],
            "fallback_paths": [
                str(Path.home() / ".local" / "bin" / "claude"),
                "/opt/homebrew/bin/claude",
                "/usr/local/bin/claude"
            ],
            "auth_mode": AuthMode.LOGIN_SESSION,
            "session_markers": [str(Path.home() / ".claude"), str(Path.home() / ".config" / "claude")],
            "capabilities": {
                AgentCapability.READ_REPOSITORY,
                AgentCapability.WRITE_REPOSITORY,
                AgentCapability.PROPOSE_EDITS,
                AgentCapability.RUN_COMMANDS,
                AgentCapability.RUN_TESTS,
                AgentCapability.ARTIFACT_GENERATION,
                AgentCapability.STRUCTURED_DECISION,
            },
            "supported_roles": {
                AgentRole.ENGINEERING_EXECUTION,
                AgentRole.LEAD_ARCHITECT,
                AgentRole.REVIEW_AGENT,
            },
            "supports_non_interactive": True,
            "supports_structured_output": True,
            "supports_sandbox": True,
            "supports_unattended": True,
        },
    }

    @classmethod
    def _find_executable(cls, exec_names: List[str], fallback_paths: List[str]) -> Optional[str]:
        """Finds executable path on PATH or known fallback locations."""
        for name in exec_names:
            p = shutil.which(name)
            if p and os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        for fallback in fallback_paths:
            if fallback and os.path.isfile(fallback) and os.access(fallback, os.X_OK):
                return fallback
        return None

    @classmethod
    def _extract_version(cls, executable: str) -> Optional[str]:
        """Safely extracts tool version string using --version."""
        try:
            res = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            out = (res.stdout or res.stderr).strip()
            if out:
                # Return first line of version output
                return out.splitlines()[0].strip()
        except Exception:
            pass
        return None

    @classmethod
    def _detect_auth_status(cls, spec: Dict[str, Any], executable: Optional[str]) -> AuthStatus:
        """Non-destructively checks if an active login session or credential marker is present."""
        if not executable:
            return AuthStatus.NOT_AUTHENTICATED

        # Check session marker directory presence without reading/exposing secrets
        session_markers = spec.get("session_markers", [])
        for marker in session_markers:
            p = Path(marker)
            if p.exists():
                return AuthStatus.AUTHENTICATED

        return AuthStatus.UNKNOWN

    @classmethod
    def inspect_provider(cls, provider_id: str) -> ProviderDescriptor:
        """
        Inspects a specific CLI provider on the host machine safely and non-destructively.
        Guaranteed never to raise exceptions on missing tools.
        """
        spec = cls.KNOWN_CLI_SPECS.get(provider_id)
        if not spec:
            return ProviderDescriptor(
                provider_id=provider_id,
                display_name=f"Custom CLI ({provider_id})",
                transport=ProviderTransport.CLI,
                auth_mode=AuthMode.PROVIDER_DEPENDENT,
                installation_status=InstallationStatus.UNKNOWN,
                auth_status=AuthStatus.UNKNOWN,
                availability=AvailabilityStatus.UNAVAILABLE,
            )

        executable = cls._find_executable(spec.get("exec_names", []), spec.get("fallback_paths", []))
        if executable:
            version = cls._extract_version(executable)
            auth_status = cls._detect_auth_status(spec, executable)
            installation_status = InstallationStatus.INSTALLED
            if spec["auth_mode"] == AuthMode.PROVIDER_DEPENDENT:
                state = ProviderState.AVAILABLE
                availability = AvailabilityStatus.AVAILABLE
            elif auth_status == AuthStatus.AUTHENTICATED:
                state = ProviderState.AVAILABLE
                availability = AvailabilityStatus.AVAILABLE
            else:
                state = ProviderState.AUTH_REQUIRED
                availability = AvailabilityStatus.DEGRADED
        else:
            version = None
            auth_status = AuthStatus.NOT_AUTHENTICATED
            installation_status = InstallationStatus.NOT_INSTALLED
            state = ProviderState.NOT_INSTALLED
            availability = AvailabilityStatus.UNAVAILABLE

        return ProviderDescriptor(
            provider_id=provider_id,
            display_name=spec["display_name"],
            transport=ProviderTransport.CLI,
            auth_mode=spec["auth_mode"],
            state=state,
            installation_status=installation_status,
            auth_status=auth_status,
            availability=availability,
            capabilities=set(spec.get("capabilities", set())),
            supported_roles=set(spec.get("supported_roles", set())),
            executable=executable,
            version=version,
            supports_non_interactive=spec.get("supports_non_interactive", True),
            supports_structured_output=spec.get("supports_structured_output", True),
            supports_sandbox=spec.get("supports_sandbox", True),
            supports_unattended=spec.get("supports_unattended", True),
            metadata={"session_markers_checked": len(spec.get("session_markers", []))},
        )

    @classmethod
    def discover_all_cli_providers(cls) -> List[ProviderDescriptor]:
        """Discovers and inspects all known CLI providers on the host system."""
        results = []
        for pid in cls.KNOWN_CLI_SPECS.keys():
            results.append(cls.inspect_provider(pid))
        return results

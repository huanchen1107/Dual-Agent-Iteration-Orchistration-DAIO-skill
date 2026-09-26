"""
Engineering Agent Adapter Factory for Generic DAIO.
Creates agent adapters dynamically based on provider configuration and environment variables.
"""

from __future__ import annotations
import os
from typing import Any, Dict, Optional

from .agent_contract import EngineeringAgentAdapter, MockEngineeringAgentAdapter
from .gemini_agent import GeminiEngineeringAgentAdapter
from .antigravity_cli_agent import AntigravityCLIAdapter, find_antigravity_cli_path


def create_engineering_agent_adapter(config: Optional[Dict[str, Any]] = None) -> EngineeringAgentAdapter:
    """
    Factory to instantiate the appropriate EngineeringAgentAdapter.
    Priority:
    1. Explicit config['provider'] ("ANTIGRAVITY_CLI", "GEMINI", "MOCK")
    2. Capability auto-detection:
       a. Antigravity CLI ('agy') if binary is installed and executable
       b. Gemini API if GEMINI_API_KEY / GOOGLE_API_KEY is present
    3. Fallback to Gemini (fails closed gracefully if unconfigured)
    """
    cfg = config or {}
    provider = cfg.get("provider", "").upper()

    if provider == "ANTIGRAVITY_CLI" or provider == "AGY":
        return AntigravityCLIAdapter(
            cli_path=cfg.get("cli_path"),
            model_name=cfg.get("model_name"),
            timeout_seconds=cfg.get("timeout_seconds", 300),
            unattended=cfg.get("unattended", True),
            sandbox=cfg.get("sandbox", True),
        )

    if provider == "GEMINI":
        return GeminiEngineeringAgentAdapter(
            api_key=cfg.get("api_key"),
            model_name=cfg.get("model_name", "gemini-2.5-pro")
        )

    if provider == "MOCK":
        return MockEngineeringAgentAdapter()

    # Auto-detection when provider is not explicitly set or set to AUTO
    if not provider or provider == "AUTO":
        cli_bin = find_antigravity_cli_path()
        if cli_bin:
            return AntigravityCLIAdapter(
                cli_path=cli_bin,
                model_name=cfg.get("model_name"),
                timeout_seconds=cfg.get("timeout_seconds", 300),
                unattended=cfg.get("unattended", True),
                sandbox=cfg.get("sandbox", True),
            )

        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return GeminiEngineeringAgentAdapter(
                api_key=cfg.get("api_key"),
                model_name=cfg.get("model_name", "gemini-2.5-pro")
            )

    # Default fallback
    return GeminiEngineeringAgentAdapter(
        api_key=cfg.get("api_key"),
        model_name=cfg.get("model_name", "gemini-2.5-pro")
    )


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
from .gemini_cli_agent import GeminiCLIAdapter, find_gemini_cli_path
from .codex_cli_agent import CodexCLIAdapter, find_codex_cli_path
from .bridge import ArchitectBridgeAdapter, ChromeCDPBridgeAdapter, MockArchitectBridgeAdapter, GeminiArchitectBridgeAdapter


def create_engineering_agent_adapter(config: Optional[Dict[str, Any]] = None) -> EngineeringAgentAdapter:
    """
    Factory to instantiate the appropriate EngineeringAgentAdapter.
    Priority:
    1. Explicit config['provider'] ("ANTIGRAVITY_CLI", "GEMINI_CLI", "CODEX_CLI", "GEMINI", "MOCK")
    2. Capability auto-detection:
       a. Antigravity CLI ('agy') if binary is installed and executable
       b. Gemini CLI ('gemini') if binary is installed and executable
       c. Codex CLI ('codex') if binary is installed and executable
       d. Gemini API if GEMINI_API_KEY / GOOGLE_API_KEY is present
    3. Fallback to Gemini (fails closed gracefully if unconfigured)
    """
    cfg = config or {}
    provider = cfg.get("provider", "").upper()

    if provider in ("ANTIGRAVITY_CLI", "AGY", "ANTIGRAVITY"):
        return AntigravityCLIAdapter(
            cli_path=cfg.get("cli_path"),
            model_name=cfg.get("model_name"),
            timeout_seconds=cfg.get("timeout_seconds", 300),
            unattended=cfg.get("unattended", True),
            sandbox=cfg.get("sandbox", True),
        )

    if provider == "GEMINI_CLI":
        return GeminiCLIAdapter(
            cli_path=cfg.get("cli_path"),
            model_name=cfg.get("model_name"),
            timeout_seconds=cfg.get("timeout_seconds", 300),
            unattended=cfg.get("unattended", True),
            sandbox=cfg.get("sandbox", True),
        )

    if provider in ("CODEX_CLI", "CODEX"):
        return CodexCLIAdapter(
            cli_path=cfg.get("cli_path"),
            model_name=cfg.get("model_name"),
            timeout_seconds=cfg.get("timeout_seconds", 300),
            unattended=cfg.get("unattended", True),
            sandbox=cfg.get("sandbox", True),
        )

    if provider in ("GEMINI", "GEMINI_API"):
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

        gemini_bin = find_gemini_cli_path()
        if gemini_bin:
            return GeminiCLIAdapter(
                cli_path=gemini_bin,
                model_name=cfg.get("model_name"),
                timeout_seconds=cfg.get("timeout_seconds", 300),
                unattended=cfg.get("unattended", True),
                sandbox=cfg.get("sandbox", True),
            )

        codex_bin = find_codex_cli_path()
        if codex_bin:
            return CodexCLIAdapter(
                cli_path=codex_bin,
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


def create_architect_bridge_adapter(config: Optional[Dict[str, Any]] = None) -> ArchitectBridgeAdapter:
    """
    Factory to instantiate the appropriate ArchitectBridgeAdapter.
    Priority:
    1. Explicit config['provider'] ("MOCK", "TEST", "GEMINI", "CHROME_CDP", "CHATGPT_WEB", "CDP")
    2. Fallback to ChromeCDPBridgeAdapter
    """
    cfg = config or {}
    provider = cfg.get("provider", "").upper()

    if provider in ("MOCK", "TEST"):
        return MockArchitectBridgeAdapter(canned_decisions=cfg.get("canned_decisions"))

    if provider == "GEMINI":
        return GeminiArchitectBridgeAdapter(
            api_key=cfg.get("api_key"),
            model_name=cfg.get("model_name", "gemini-2.5-pro")
        )

    if provider in ("CHROME_CDP", "CHATGPT_WEB", "CDP", "CHROME"):
        return ChromeCDPBridgeAdapter(
            endpoint=cfg.get("endpoint"),
            url_pattern=cfg.get("url_pattern", "chatgpt.com"),
            cdp_port=cfg.get("cdp_port", 9222),
            max_discovery_retries=cfg.get("max_discovery_retries", 3),
        )

    # Default fallback
    return ChromeCDPBridgeAdapter(
        endpoint=cfg.get("endpoint"),
        url_pattern=cfg.get("url_pattern", "chatgpt.com"),
        cdp_port=cfg.get("cdp_port", 9222),
        max_discovery_retries=cfg.get("max_discovery_retries", 3),
    )




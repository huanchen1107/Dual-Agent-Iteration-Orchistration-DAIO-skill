"""
Engineering Agent Adapter Factory for Generic DAIO.
Creates agent adapters dynamically based on provider configuration and environment variables.
"""

from __future__ import annotations
import os
from typing import Any, Dict, Optional

from .agent_contract import EngineeringAgentAdapter, MockEngineeringAgentAdapter
from .gemini_agent import GeminiEngineeringAgentAdapter


def create_engineering_agent_adapter(config: Optional[Dict[str, Any]] = None) -> EngineeringAgentAdapter:
    """
    Factory to instantiate the appropriate EngineeringAgentAdapter.
    Priority:
    1. Explicit config['provider']
    2. Environment detection (GEMINI_API_KEY / GOOGLE_API_KEY)
    3. Fallback to Mock / Fail-closed
    """
    cfg = config or {}
    provider = cfg.get("provider", "").upper()

    if provider == "GEMINI" or (not provider and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))):
        return GeminiEngineeringAgentAdapter(
            api_key=cfg.get("api_key"),
            model_name=cfg.get("model_name", "gemini-2.5-pro")
        )

    if provider == "MOCK":
        return MockEngineeringAgentAdapter()

    # Default to Gemini adapter which will fail-closed gracefully if credentials missing
    return GeminiEngineeringAgentAdapter(
        api_key=cfg.get("api_key"),
        model_name=cfg.get("model_name", "gemini-2.5-pro")
    )

"""MCP adapter — the same one-click API, exposed as tools to an agent."""
from __future__ import annotations

from .server import TOOLS, call_tool, handle_message, serve_stdio

__all__ = ["TOOLS", "call_tool", "handle_message", "serve_stdio"]

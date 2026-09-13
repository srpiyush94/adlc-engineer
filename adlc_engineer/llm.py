"""LLM and tracing setup. Mirrors simple_agent/agent.py's pattern (duplicated, not imported)."""

import os

from langchain_google_genai import ChatGoogleGenerativeAI


def get_langfuse_handler():
    """Build a Langfuse callback handler if credentials are configured, else None."""
    if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        from langfuse.callback import CallbackHandler
    return CallbackHandler()


def build_llm():
    model_name = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
    return ChatGoogleGenerativeAI(model=model_name, timeout=60, max_retries=3)

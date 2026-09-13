"""A simple LangGraph agent using Gemini Flash with tool-calling and Langfuse tracing."""

import os
from typing import Annotated, TypedDict

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from tools import TOOLS

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to two tools: `calculator` for "
    "arithmetic and `web_search` for looking up information. Use a tool whenever "
    "it would help answer the question accurately; otherwise answer directly."
)

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def get_langfuse_handler():
    """Build a Langfuse callback handler if credentials are configured, else None."""
    if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        from langfuse.callback import CallbackHandler
    return CallbackHandler()


def build_agent():
    """Build and compile the LangGraph agent graph."""
    model_name = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    llm = ChatGoogleGenerativeAI(model=model_name)
    llm_with_tools = llm.bind_tools(TOOLS)

    def think(state: AgentState):
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def use_tool(state: AgentState):
        last_message = state["messages"][-1]
        tool_messages = []
        for tool_call in last_message.tool_calls:
            tool_fn = TOOLS_BY_NAME.get(tool_call["name"])
            if tool_fn is None:
                content = f"Unknown tool: {tool_call['name']}"
            else:
                try:
                    content = tool_fn.invoke(tool_call["args"])
                except Exception as exc:
                    content = f"Error running tool '{tool_call['name']}': {exc}"
            tool_messages.append(
                ToolMessage(content=str(content), tool_call_id=tool_call["id"])
            )
        return {"messages": tool_messages}

    def route_after_think(state: AgentState):
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "use_tool"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("think", think)
    graph.add_node("use_tool", use_tool)

    graph.add_edge(START, "think")
    graph.add_conditional_edges(
        "think", route_after_think, {"use_tool": "use_tool", END: END}
    )
    graph.add_edge("use_tool", "think")

    return graph.compile()

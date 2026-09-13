"""Tools available to the agent: a calculator and a mocked web search."""

import ast
import operator

from langchain_core.tools import tool

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression, e.g. '2 + 2 * 3' or '(10 - 4) / 2'.

    Supports +, -, *, /, %, ** and parentheses. Returns the numeric result as a string.
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body)
        return str(result)
    except Exception as exc:
        return f"Error evaluating expression '{expression}': {exc}"


_MOCK_SEARCH_RESULTS = {
    "langgraph": (
        "LangGraph is a library for building stateful, multi-actor applications with LLMs, "
        "built on top of LangChain. It models agent workflows as graphs of nodes and edges."
    ),
    "gemini": (
        "Gemini is Google's family of multimodal large language models, including the "
        "fast and cost-efficient 'Flash' variants suited for low-latency applications."
    ),
    "langfuse": (
        "Langfuse is an open-source observability and tracing platform for LLM applications, "
        "used to monitor, debug, and evaluate agent runs."
    ),
}


@tool
def web_search(query: str) -> str:
    """Search the web for information about a topic (mocked for this demo).

    Returns a short canned summary for known topics, or a generic placeholder
    result otherwise. Useful for questions requiring lookups beyond arithmetic.
    """
    query_lower = query.lower()
    for keyword, summary in _MOCK_SEARCH_RESULTS.items():
        if keyword in query_lower:
            return f"[mocked search result for '{query}']: {summary}"
    return (
        f"[mocked search result for '{query}']: No specific mock data available. "
        "This is a placeholder result since web_search is not connected to a real search API."
    )


TOOLS = [calculator, web_search]

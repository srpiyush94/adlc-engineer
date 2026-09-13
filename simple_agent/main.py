"""Run the LangGraph agent: three automatic test questions, then an interactive loop."""

from dotenv import load_dotenv

load_dotenv()
from langchain_core.messages import HumanMessage

from agent import build_agent, get_langfuse_handler  # noqa: E402  (must load env first)

TEST_QUESTIONS = [
    "What is (24 + 6) * 3 / 2?",
    "Search for information about LangGraph.",
    "What is the capital of France?",
]


def _as_text(content) -> str:
    """Flatten LangChain message content (str, or list of content blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def ask(agent, callbacks, question: str) -> str:
    config = {"callbacks": callbacks} if callbacks else {}
    result = agent.invoke({"messages": [HumanMessage(content=question)]}, config=config)
    return _as_text(result["messages"][-1].content)


def main():
    agent = build_agent()
    handler = get_langfuse_handler()
    callbacks = [handler] if handler else []

    if handler is None:
        print("(Langfuse credentials not found in .env — running without tracing.)\n")

    print("=== Running 3 automatic test questions ===\n")
    for question in TEST_QUESTIONS:
        print(f"> {question}")
        answer = ask(agent, callbacks, question)
        print(f"{answer}\n")

    print("=== Interactive mode (type 'exit' or 'quit' to stop) ===")
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break
        answer = ask(agent, callbacks, question)
        print(answer)


if __name__ == "__main__":
    main()

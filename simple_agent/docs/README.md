# Documentation index

Detailed docs explaining how `simple_agent` works, split by concern:

1. [What makes this an "agent"](01-what-makes-it-an-agent.md) — the concept:
   perceive → think → act → observe, and why a loop + tool choice is what
   separates an agent from a single LLM call.
2. [LangGraph anatomy](02-langgraph-anatomy.md) — the mechanics: state schema,
   nodes, edges, conditional routing, compilation.
3. [Execution flow](03-execution-flow.md) — a step-by-step trace of both
   possible paths (direct answer vs. tool-call loop), with sequence diagrams
   and exact code references.
4. [Tracing and observability](04-tracing-and-observability.md) — how the
   Langfuse callback hooks into LangGraph/LangChain and what shows up in the
   Langfuse UI.

For setup and running instructions, see the top-level [README](../README.md).

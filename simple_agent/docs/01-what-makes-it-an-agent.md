# What makes this an "agent"?

A plain call to an LLM is a function: text in, text out. Nothing here would
call that an agent — there's no way for the model to look anything up, do
exact math, or change what it does next based on new information.

`simple_agent` becomes an *agent* because it adds four things around the raw
model call:

| Ingredient | Where it lives | Role |
|---|---|---|
| **Reasoning engine** | Gemini Flash (`ChatGoogleGenerativeAI`) | Decides *what* to do next: answer, or call a tool. |
| **Actions** | `tools.py` (`calculator`, `web_search`) | Things the model can *do* beyond generating text. |
| **Memory / state** | `AgentState.messages` | The running record of everything said and done, so each step has full context. |
| **Control loop** | the LangGraph graph in `agent.py` | Repeats "think, maybe act" until the model is done — the model, not the code, decides when to stop. |

## The perceive → think → act → observe loop

This is the classic agent loop, and you can map it directly onto the two
graph nodes:

```
perceive  →  the incoming HumanMessage (or a ToolMessage from the last round)
think     →  "think" node: Gemini reads the message history, decides:
                 (a) answer now, or
                 (b) call one or more tools
act       →  "use_tool" node: actually runs the requested tool(s)
observe   →  the tool's result is appended to history as a ToolMessage,
             then control returns to "think" — which now perceives the
             tool's output and repeats the cycle
```

The loop terminates the moment `think` produces a plain-text response with no
`tool_calls` — at that point there is nothing left to *act* on, so the graph
routes to `END` instead of `use_tool`.

## Why tool-calling is the key mechanism

`llm.bind_tools(TOOLS)` (see `agent.py:41`) is what turns a passive
text-completion model into something that can choose actions. Concretely:

1. Each `@tool`-decorated function in `tools.py` has a name, a docstring, and
   type-hinted parameters. LangChain turns that into a JSON schema.
2. `bind_tools` attaches those schemas to every request sent to Gemini, as
   part of the API's native function-calling feature.
3. Gemini's response can then be either normal text, or a structured
   `tool_calls` payload (`[{"name": "calculator", "args": {"expression": "..."}}, ...]`)
   — the model is choosing an action from a menu it was given, not writing
   free-form code.
4. LangChain surfaces that structured payload as `AIMessage.tool_calls`, which
   is exactly the field `route_after_think` (`agent.py:67-71`) inspects to
   decide whether to loop back into `use_tool`.

Without `bind_tools`, the model could still *talk about* using a calculator,
but there would be no structured signal for the code to act on — it would
just be text the graph doesn't know how to interpret. That structured
signal is what makes the "act" step possible, and therefore what makes this
an agent rather than a chatbot.

## What's deliberately *not* here

This is a minimal, single-agent example, so a few things a more complex
system might add are intentionally left out:

- **No planning ahead** — the model decides one action at a time, not a
  multi-step plan up front. This is a reactive (ReAct-style) loop, not a
  planner.
- **No persistent memory across runs** — `AgentState` lives only for the
  duration of one `agent.invoke(...)` call in `main.py`; there's no
  checkpointer, so history doesn't survive between separate questions in the
  test/interactive loop.
- **No sub-agents or delegation** — one model, one loop. LangGraph supports
  multi-agent graphs, but this example intentionally stays to the smallest
  loop that still qualifies as "agentic."

See [02-langgraph-anatomy.md](02-langgraph-anatomy.md) for how the loop above
is actually implemented as a graph.

# LangGraph anatomy

This doc covers the LangGraph-specific mechanics used in `agent.py` —
state, nodes, edges, and compilation.

## 1. State: the single source of truth

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
```

`agent.py:22-23`

Every node in the graph reads from and writes to this one shared state. There
is only one field, `messages`, and it's annotated with `add_messages`, a
LangGraph **reducer**. Reducers control *how* a node's return value gets
merged into the existing state, rather than replacing it wholesale:

- Without a reducer, returning `{"messages": [new_msg]}` from a node would
  **overwrite** `state["messages"]` entirely, wiping history.
- With `add_messages`, LangGraph instead **appends** `new_msg` to the
  existing list (and, if a returned message reuses an existing message's
  `id`, it *updates* that message in place instead of duplicating it — not
  used here, but it's why `add_messages` is the standard choice for chat
  history).

This is why every node function below only ever returns the *new* messages
it produced, never the full accumulated list.

## 2. Nodes: plain functions over state

A node is just a function `(state) -> partial_state_update`. This graph has
two:

### `think` (`agent.py:43-48`)

```python
def think(state: AgentState):
    messages = state["messages"]
    if not any(isinstance(m, SystemMessage) for m in messages):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}
```

- Prepends the system prompt on the *first* call only (checked by scanning
  for an existing `SystemMessage`, so it isn't duplicated on every loop
  iteration).
- Calls the tool-bound Gemini model with the full message history.
- Returns exactly one new message: the model's `AIMessage` response.

### `use_tool` (`agent.py:50-65`)

```python
def use_tool(state: AgentState):
    last_message = state["messages"][-1]
    tool_messages = []
    for tool_call in last_message.tool_calls:
        tool_fn = TOOLS_BY_NAME.get(tool_call["name"])
        ...
        tool_messages.append(ToolMessage(content=str(content), tool_call_id=tool_call["id"]))
    return {"messages": tool_messages}
```

- Reads the *last* message (guaranteed by the routing logic below to be an
  `AIMessage` with `tool_calls`).
- Loops over every tool call the model requested in that single turn — Gemini
  can request more than one tool call at once, and this handles all of them.
- Looks each one up by name in `TOOLS_BY_NAME` (`agent.py:19`, built once from
  the `TOOLS` list in `tools.py`), invokes it, and wraps the result in a
  `ToolMessage`. The `tool_call_id` link is what lets the model correctly
  associate each result with the call that produced it, especially when
  multiple tools were called in the same turn.
- Any exception from a tool is caught and turned into an error string passed
  back to the model as the tool's "result" — the model sees the failure and
  can react to it (e.g. try something else) instead of the whole graph
  crashing.

## 3. Conditional routing: the decision point

```python
def route_after_think(state: AgentState):
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "use_tool"
    return END
```

`agent.py:67-71`

This is a **routing function**, not a node — it doesn't modify state, it just
inspects the latest `AIMessage` and returns a string naming where to go next.
`getattr(..., "tool_calls", None)` defends against message types that don't
have a `tool_calls` attribute at all, though in practice the last message
here is always the `AIMessage` `think` just produced.

## 4. Wiring it together

```python
graph = StateGraph(AgentState)
graph.add_node("think", think)
graph.add_node("use_tool", use_tool)

graph.add_edge(START, "think")
graph.add_conditional_edges("think", route_after_think, {"use_tool": "use_tool", END: END})
graph.add_edge("use_tool", "think")

return graph.compile()
```

`agent.py:73-83`

- `add_edge(START, "think")` — every invocation begins at `think`.
- `add_conditional_edges("think", route_after_think, {...})` — after `think`
  runs, call `route_after_think` on the resulting state; the dict maps its
  possible return values (`"use_tool"` or the `END` sentinel) to actual graph
  destinations. This mapping is required — LangGraph needs to know the full
  set of nodes a conditional edge might target ahead of time.
- `add_edge("use_tool", "think")` — a plain, unconditional edge: after any
  tool runs, always go back to `think` so the model can see the result.
- `graph.compile()` turns the node/edge definitions into a runnable object
  (`agent.invoke(...)`, used throughout `main.py`) with cycle support — the
  `use_tool → think` edge combined with `think`'s conditional edge is what
  allows this graph to loop an arbitrary number of times, unlike a simple
  linear LangChain chain.

See [03-execution-flow.md](03-execution-flow.md) for a full runtime trace
through this graph on real input.

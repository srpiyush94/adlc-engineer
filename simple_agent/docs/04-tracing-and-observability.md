# Tracing and observability

## How the handler gets created

```python
def get_langfuse_handler():
    if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        from langfuse.callback import CallbackHandler
    return CallbackHandler()
```

`agent.py:26-34`

- If either Langfuse key is missing from `.env`, this returns `None` and
  `main.py` runs with an empty callback list — tracing is opt-in, not
  required to run the agent.
- The `try/except` handles two different Langfuse SDK versions: newer
  releases (Langfuse v3+, OpenTelemetry-based) expose the handler at
  `langfuse.langchain.CallbackHandler`; older ones used
  `langfuse.callback.CallbackHandler`. Whichever is installed, the rest of
  the code doesn't need to know — it just gets *a* `CallbackHandler`.
- `CallbackHandler()` reads `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and
  `LANGFUSE_HOST` from the environment itself (already loaded by
  `load_dotenv()` at the top of `main.py`), so no arguments need to be
  passed explicitly here.

## How it attaches to a run

```python
result = agent.invoke({"messages": [...]}, config={"callbacks": callbacks})
```

`main.py`'s `ask()` function passes the handler as a **LangChain callback**,
using the standard `config={"callbacks": [...]}` mechanism that every
`Runnable.invoke(...)` call accepts (LangGraph graphs are `Runnable`s too).
Because callbacks propagate automatically to everything invoked underneath —
every node function, every `llm_with_tools.invoke(...)` call inside
`think` — a single handler passed at the top captures the *entire* graph
run without any node needing to know tracing exists.

## What shows up in Langfuse

Each call to `agent.invoke(...)` produces one **trace**, containing:

- A span for the graph run itself.
- A nested span per node execution (`think`, `use_tool`), for each pass
  through the loop — so a tool-call round trip (see
  [03-execution-flow.md](03-execution-flow.md#path-b--one-tool-call-round-trip))
  shows up as `think → use_tool → think`, matching the actual control flow.
- A **generation** record inside each `think` span for the underlying Gemini
  API call — capturing the prompt sent, the raw completion, token usage, and
  latency.

This makes it possible to see, per question: how many think/tool round
trips it took, exactly what the model was asked at each step, what it
decided to do, and how long each part took — without adding any print
statements to the agent code itself.

## Region matters: US vs EU Langfuse Cloud

Langfuse Cloud runs as two independent deployments — US
(`https://us.cloud.langfuse.com`) and EU (`https://cloud.langfuse.com`) —
with separate keys per region. Pointing a US-region key at the EU host (or
vice versa) fails auth with an HTTP 401 on span export, even though the key
itself is valid. `.env`'s `LANGFUSE_HOST` must match wherever the keys shown
in the Langfuse project settings were actually created; this project uses
the US host.

## Running without tracing

Leaving `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` blank in `.env` is a
fully supported mode — `main.py` prints a one-line notice
(`"Langfuse credentials not found in .env — running without tracing."`) and
proceeds with `callbacks = []`, which is a no-op for `agent.invoke`.

# BGE-M3 routing module

This folder contains a small, isolated routing module for the GraphRAG backend.

## What it does

1. Receives a user question.
2. Uses BGE-M3 to compare the question against two generic criteria:
   - `local`: specific entity/event/concept/detail questions.
   - `global`: whole document/unit/topic/summary/flow questions.
3. Applies lightweight guard rules:
   - Direct GraphRAG entity name match usually forces `local`.
   - Broad summary/flow/theme cues usually force `global`.
   - Comparison/relation cues with specific entities stay `local`.
4. Returns the final `local` or `global` mode plus diagnostic metadata.

BGE-M3 is only a router. It does not generate answers and it does not choose
community reports. Once a mode is selected, GraphRAG local/global search should
build the context and call the configured LLM.

## Files

- `routing_bge.py`: BGE-M3 local/global router.
- `graphrag_search_client.py`: reference wrapper around existing `warm_query.py`.
- `example_app.py`: standalone FastAPI example, not meant to replace `backend/app.py`.
- `requirements-routing.txt`: packages needed only for the router.

## Environment variables

```bash
BGE_MODEL_PATH=/path/to/bge-m3
BGE_DEVICE=cpu
GRAPHRAG_REPO_ROOT=/path/to/graphrag
```

Use `BGE_DEVICE=cuda` only when the server has a CUDA-enabled PyTorch build and
enough GPU memory.

## Integration point

The current backend query path is in `backend/serve.py`. The intended flow is:

```text
POST /query
-> resolve snapshot
-> BGE route question to local/global
-> call GraphRAG search with that mode
-> return answer plus route metadata
```

For the production backend, prefer integrating `BGERouter` into the existing
`backend/serve.py` state and engine loading path instead of running `example_app.py`
as a second server.


from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import Any


class GraphRAGSearchClient:
    """Wrapper around the repository's official GraphRAG search engines.

    This is a reference adapter for routing integration. The existing backend
    can either use this wrapper or call its own backend.query load_engine path.
    In both cases, GraphRAG itself remains responsible for building local/global
    context and for selecting community reports during global search.
    """

    def __init__(self, repo_root: str | Path | None = None):
        self.repo_root = Path(
            repo_root or os.getenv("GRAPHRAG_REPO_ROOT", ".")
        ).resolve()
        # warm_query.py was renamed to backend/query.py in the backend refactor;
        # the legacy module API (DFS/_engine/ask) still lives there.
        warm_query_path = self.repo_root / "backend" / "query.py"
        if not warm_query_path.exists():
            raise FileNotFoundError(f"backend/query.py not found: {warm_query_path}")

        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))

        spec = importlib.util.spec_from_file_location(
            "warm_query_runtime", warm_query_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot import backend/query.py: {warm_query_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.warm_query = module

    def entity_titles(self) -> list[str]:
        entities = self.warm_query.DFS.get("entities")
        if entities is None or "title" not in entities.columns:
            return []
        return [
            str(x).strip()
            for x in entities["title"].dropna().astype(str).tolist()
            if str(x).strip()
        ]

    def search(self, question: str, mode: str) -> dict[str, Any]:
        if mode not in {"local", "global"}:
            raise ValueError("mode must be 'local' or 'global'")

        engine = self.warm_query._engine(mode)
        started = time.perf_counter()
        result = asyncio.run(engine.search(question))
        elapsed = time.perf_counter() - started

        return {
            "mode": mode,
            "question": question,
            "answer": getattr(result, "response", str(result)),
            "elapsed_seconds": round(elapsed, 3),
            "llm_calls": getattr(result, "llm_calls", None),
            "prompt_tokens": getattr(result, "prompt_tokens", None),
            "output_tokens": getattr(result, "output_tokens", None),
        }


"""
warm-load GraphRAG snapshot + REPL/cells for fast iteration.

CLI(graphrag query)는 질문마다 새 프로세스가 떠서 import + parquet + LanceDB +
엔진 초기화가 매번 반복돼 질문당 수십 초가 걸린다. 이 스크립트는 그걸 한 번만
로드해두고, 이후엔 ask()만 호출해 몇 초 만에 답을 받는 게 목적이다.

사용 방식 (둘 중 하나):
  1) python warm_query.py
     셀 1+2 자동 실행 후, 끝에 REPL이 떠서 질문 입력만 받음.
  2) VSCode/PyCharm interactive 셀 단위(`# %%`)로 실행.
     셀 2를 한 번 돌리고 셀 3을 질문 바꿔가며 반복.

가리키는 인덱스(스냅샷):
  output_storage.base_dir = results/snapshots/repro_run3
  vector_store.db_uri     = results/snapshots/repro_run3/lancedb
settings.yaml은 건드리지 않고, in-memory cli_overrides로만 조정한다.
"""

# %% [셀 1] import + 환경 ===========================================
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
from graphrag_storage import create_storage
from graphrag_storage.tables.table_provider_factory import create_table_provider

from graphrag.config.embeddings import (
    community_full_content_embedding,
    entity_description_embedding,
    text_unit_text_embedding,
)
from graphrag.config.load_config import load_config
from graphrag.data_model.data_reader import DataReader
from graphrag.query.factory import (
    get_basic_search_engine,
    get_drift_search_engine,
    get_global_search_engine,
    get_local_search_engine,
)
from graphrag.query.indexer_adapters import (
    read_indexer_communities,
    read_indexer_covariates,
    read_indexer_entities,
    read_indexer_relationships,
    read_indexer_report_embeddings,
    read_indexer_reports,
    read_indexer_text_units,
)
from graphrag.utils.api import get_embedding_store, load_search_prompt


def _patch_basic_search() -> None:
    """graphrag 3.1.0 BasicSearch.search() 의 await 누락 패치.

    search.py line 94에서 self.model.completion_async(...) 결과가 coroutine인데
    await 없이 async for로 넘기다 TypeError. 같은 파일 stream_search는 await 붙어
    정상. CLI(api.basic_search_streaming)는 stream_search 경로라 영향 없음. 우리는
    engine.search()를 직접 부르므로 패치 필요. venv 안 건드리고 monkey patch.
    """
    from graphrag.query.structured_search.basic_search.search import BasicSearch

    if getattr(BasicSearch.search, "_patched", False):
        return

    _orig = BasicSearch.search

    async def _patched(self, query, conversation_history=None, **kwargs):  # type: ignore[no-untyped-def]
        import time as _t
        from graphrag.query.structured_search.base import SearchResult

        start = _t.time()
        ctx = self.context_builder.build_context(
            query=query,
            conversation_history=conversation_history,
            **kwargs,
            **self.context_builder_params,
        )
        search_prompt = self.system_prompt.format(
            context_data=ctx.context_chunks, response_type=self.response_type
        )
        from graphrag_llm.utils import CompletionMessagesBuilder
        msgs = (
            CompletionMessagesBuilder()
            .add_system_message(search_prompt)
            .add_user_message(query)
        ).build()
        stream = await self.model.completion_async(
            messages=msgs, stream=True, **self.model_params
        )
        response = ""
        async for chunk in stream:
            piece = chunk.choices[0].delta.content or ""
            for cb in self.callbacks:
                cb.on_llm_new_token(piece)
            response += piece
        for cb in self.callbacks:
            cb.on_context(ctx.context_records)
        return SearchResult(
            response=response,
            context_data=ctx.context_records,
            context_text=ctx.context_chunks,
            completion_time=_t.time() - start,
            llm_calls=1,
            prompt_tokens=len(self.tokenizer.encode(search_prompt)),
            output_tokens=len(self.tokenizer.encode(response)),
            llm_calls_categories={"build_context": ctx.llm_calls, "response": 1},
            prompt_tokens_categories={"build_context": ctx.prompt_tokens,
                                     "response": len(self.tokenizer.encode(search_prompt))},
            output_tokens_categories={"build_context": ctx.output_tokens,
                                     "response": len(self.tokenizer.encode(response))},
        )

    _patched._patched = True  # type: ignore[attr-defined]
    BasicSearch.search = _patched
    print("[patch] BasicSearch.search() await 누락 monkey patch 적용")


_patch_basic_search()


ROOT = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
SNAPSHOT = ROOT / "results" / "snapshots" / "repro_run3"

if not SNAPSHOT.exists():
    sys.exit(f"[STOP] snapshot dir not found: {SNAPSHOT}")
if not (SNAPSHOT / "lancedb").exists():
    sys.exit(f"[STOP] lancedb missing in snapshot: {SNAPSHOT / 'lancedb'}")

CLI_OVERRIDES: dict[str, Any] = {
    "output_storage": {"base_dir": str(SNAPSHOT)},
    "vector_store": {"db_uri": str(SNAPSHOT / "lancedb")},
}

print(f"[init] root     = {ROOT}")
print(f"[init] snapshot = {SNAPSHOT}")

config = load_config(root_dir=ROOT, cli_overrides=CLI_OVERRIDES)
print(f"[init] config loaded, vector_store.db_uri = {config.vector_store.db_uri}")


# %% [셀 2] warm load: parquet + LanceDB + 엔진 ====================
# 이 셀은 한 번만 돌리면 끝. 결과(DFS, ENGINES)는 모듈 전역에 남는다.

def _read_all_outputs() -> dict[str, pd.DataFrame | None]:
    storage_obj = create_storage(config.output_storage)
    table_provider = create_table_provider(config.table_provider, storage=storage_obj)
    reader = DataReader(table_provider)
    out: dict[str, pd.DataFrame | None] = {}
    for name in (
        "entities",
        "communities",
        "community_reports",
        "text_units",
        "relationships",
        "documents",
    ):
        out[name] = asyncio.run(getattr(reader, name)())
    out["covariates"] = (
        asyncio.run(reader.covariates())
        if asyncio.run(table_provider.has("covariates"))
        else None
    )
    return out


t0 = time.perf_counter()
DFS = _read_all_outputs()
print(
    f"[warm] parquets loaded in {time.perf_counter() - t0:.1f}s: "
    f"entities={len(DFS['entities'])}, "
    f"communities={len(DFS['communities'])}, "
    f"reports={len(DFS['community_reports'])}, "
    f"text_units={len(DFS['text_units'])}, "
    f"relationships={len(DFS['relationships'])}, "
    f"covariates={'-' if DFS['covariates'] is None else len(DFS['covariates'])}"
)

COMMUNITY_LEVEL = 2
RESPONSE_TYPE = "Single Paragraph"

t0 = time.perf_counter()
ENTITY_DESC_STORE = get_embedding_store(
    config=config.vector_store, embedding_name=entity_description_embedding
)
TEXT_UNIT_STORE = get_embedding_store(
    config=config.vector_store, embedding_name=text_unit_text_embedding
)
FULL_CONTENT_STORE = get_embedding_store(
    config=config.vector_store, embedding_name=community_full_content_embedding
)
print(f"[warm] embedding stores opened in {time.perf_counter() - t0:.1f}s")


ENGINES: dict[str, Any] = {}


def _build_local():
    return get_local_search_engine(
        config=config,
        reports=read_indexer_reports(
            DFS["community_reports"], DFS["communities"], COMMUNITY_LEVEL
        ),
        text_units=read_indexer_text_units(DFS["text_units"]),
        entities=read_indexer_entities(
            DFS["entities"], DFS["communities"], COMMUNITY_LEVEL
        ),
        relationships=read_indexer_relationships(DFS["relationships"]),
        covariates={
            "claims": (
                read_indexer_covariates(DFS["covariates"])
                if DFS["covariates"] is not None
                else []
            )
        },
        description_embedding_store=ENTITY_DESC_STORE,
        response_type=RESPONSE_TYPE,
        system_prompt=load_search_prompt(config.local_search.prompt),
    )


def _build_global():
    return get_global_search_engine(
        config=config,
        reports=read_indexer_reports(
            DFS["community_reports"],
            DFS["communities"],
            community_level=COMMUNITY_LEVEL,
        ),
        entities=read_indexer_entities(
            DFS["entities"], DFS["communities"], community_level=COMMUNITY_LEVEL
        ),
        communities=read_indexer_communities(
            DFS["communities"], DFS["community_reports"]
        ),
        response_type=RESPONSE_TYPE,
        dynamic_community_selection=False,
        map_system_prompt=load_search_prompt(config.global_search.map_prompt),
        reduce_system_prompt=load_search_prompt(config.global_search.reduce_prompt),
        general_knowledge_inclusion_prompt=load_search_prompt(
            config.global_search.knowledge_prompt
        ),
    )


def _build_drift():
    reports = read_indexer_reports(
        DFS["community_reports"], DFS["communities"], COMMUNITY_LEVEL
    )
    read_indexer_report_embeddings(reports, FULL_CONTENT_STORE)
    return get_drift_search_engine(
        config=config,
        reports=reports,
        text_units=read_indexer_text_units(DFS["text_units"]),
        entities=read_indexer_entities(
            DFS["entities"], DFS["communities"], COMMUNITY_LEVEL
        ),
        relationships=read_indexer_relationships(DFS["relationships"]),
        description_embedding_store=ENTITY_DESC_STORE,
        response_type=RESPONSE_TYPE,
        local_system_prompt=load_search_prompt(config.drift_search.prompt),
        reduce_system_prompt=load_search_prompt(config.drift_search.reduce_prompt),
    )


def _build_basic():
    return get_basic_search_engine(
        config=config,
        text_units=read_indexer_text_units(DFS["text_units"]),
        text_unit_embeddings=TEXT_UNIT_STORE,
        response_type=RESPONSE_TYPE,
        system_prompt=load_search_prompt(config.basic_search.prompt),
    )


_BUILDERS = {
    "local": _build_local,
    "global": _build_global,
    "drift": _build_drift,
    "basic": _build_basic,
}


def _engine(method: str):
    if method not in _BUILDERS:
        raise ValueError(
            f"unknown method '{method}'. choose from {list(_BUILDERS)}"
        )
    if method not in ENGINES:
        t = time.perf_counter()
        ENGINES[method] = _BUILDERS[method]()
        print(f"[warm] engine '{method}' built in {time.perf_counter() - t:.1f}s")
    return ENGINES[method]


# local만 즉시 빌드. 나머지는 첫 호출 때 lazy.
_engine("local")
print("[warm] ready. ask('<question>', method='local'|'global'|'drift'|'basic')")


# %% [셀 3] ask: 질문 바꿔가며 반복 실행 ============================
def ask(query: str, method: str = "local") -> str:
    """질문 한 번 던지고 답 + 소요 시간 출력. 답 문자열 반환."""
    eng = _engine(method)
    t = time.perf_counter()
    result = asyncio.run(eng.search(query))
    dt = time.perf_counter() - t
    resp = result.response if hasattr(result, "response") else str(result)
    print(
        f"\n=== [{method}] {dt:.1f}s "
        f"| llm_calls={getattr(result, 'llm_calls', '?')} "
        f"| prompt_tok={getattr(result, 'prompt_tokens', '?')} "
        f"| out_tok={getattr(result, 'output_tokens', '?')} ==="
    )
    print(resp)
    return resp


# %% [REPL] script 실행 시: 입력 루프 ===============================
if __name__ == "__main__":
    print("\n--- REPL ---")
    print("형식: <method> | <질문>   (method 생략 시 local)")
    print("예:   이순신은 임진왜란에서 어떤 역할을 했나?")
    print("      global | 조선 전기 정치 세력의 변화를 6줄로")
    print("종료: 빈 줄, :q, exit\n")
    while True:
        try:
            line = input("q> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line or line in (":q", "quit", "exit"):
            break
        if "|" in line:
            head, _, query = line.partition("|")
            method = head.strip().lower() or "local"
            query = query.strip()
        else:
            method, query = "local", line
        if not query:
            continue
        try:
            ask(query, method=method)
        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}")

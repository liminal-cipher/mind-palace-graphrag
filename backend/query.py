"""
warm-load GraphRAG snapshot + REPL/cells for fast iteration.

CLI(graphrag query)는 질문마다 새 프로세스가 떠서 import + parquet + LanceDB +
엔진 초기화가 매번 반복돼 질문당 수십 초가 걸린다. 이 스크립트는 그걸 한 번만
로드해두고, 이후엔 ask()만 호출해 몇 초 만에 답을 받는 게 목적이다.

스냅샷 로드는 load_engine(snapshot)로 한다. 한 스냅샷을 통째로(config + parquet +
필요 시 LanceDB + 엔진) 로드해 격리된 LoadedEngine 번들로 돌려준다. 서로 다른
스냅샷을 같은 프로세스에서 동시에 들고 있을 수 있다(serve.py 멀티 스냅샷 레지스트리).

import 자체는 가볍다(부수효과 없음). 무거운 로드는 load_engine 호출 시점에만 돈다.

사용 방식 (둘 중 하나):
  1) python warm_query.py
     기본 스냅샷(repro_run3)을 lazy 로드하고 REPL이 떠서 질문 입력만 받음.
  2) VSCode/PyCharm interactive 셀 단위(`# %%`)로 실행.
     ask()/_engine() 첫 호출이 기본 스냅샷을 lazy 로드한다.

기본 스냅샷(레거시 모듈 API의 대상):
  snapshots/repro_run3 (config/DFS/ENGINES/_engine/ask가 가리키는 곳).
settings.yaml은 건드리지 않고, in-memory cli_overrides로만 스냅샷 경로를 바꾼다.
"""

# %% [셀 1] import + 환경 ===========================================
import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Optional, Union

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


ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd()  # backend/ -> repo root

# 레거시 모듈 API(config/DFS/ENGINES/_engine/ask)의 대상 스냅샷.
SNAPSHOT = ROOT / "results" / "snapshots" / "repro_run3"

COMMUNITY_LEVEL = 2
RESPONSE_TYPE = "Single Paragraph"

# 각 메서드가 필요로 하는 임베딩 스토어. global은 reports/entities/communities(parquet)
# 만 쓰므로 LanceDB가 전혀 필요 없다.
_STORES_FOR_METHOD: dict[str, frozenset[str]] = {
    "global": frozenset(),
    "local": frozenset({"entity_desc"}),
    "drift": frozenset({"entity_desc", "full_content"}),
    "basic": frozenset({"text_unit"}),
}


# %% [load_engine] 스냅샷 하나를 격리된 번들로 로드 ==================
class LoadedEngine:
    """한 스냅샷에 대한 격리된 로드 결과. config/DFS/임베딩 스토어/엔진을 자기
    안에 들고 있어, 서로 다른 스냅샷의 번들이 전역 상태를 공유하지 않는다.

    엔진 빌더는 이 번들의 config/dfs/stores만 읽는다. 빌드와 검색을 같은 스레드에서
    하면 LanceDB 스레드 이슈도 자연히 피해진다(serve.py 단일 워커 패턴)."""

    def __init__(
        self,
        snapshot_dir: Path,
        config: Any,
        dfs: dict[str, Optional[pd.DataFrame]],
        stores: dict[str, Any],
        response_type: str,
        synthesis_model: Optional[str] = None,
    ) -> None:
        self.snapshot_dir = snapshot_dir
        self.snapshot_name = snapshot_dir.name
        self.config = config
        self.dfs = dfs
        self.stores = stores
        self.response_type = response_type
        self.synthesis_model = synthesis_model
        self.engines: dict[str, Any] = {}

    def engine(self, method: str) -> Any:
        if method not in _BUILDERS:
            raise ValueError(
                f"unknown method '{method}'. choose from {list(_BUILDERS)}"
            )
        if method not in self.engines:
            t = time.perf_counter()
            self.engines[method] = _BUILDERS[method](self)
            print(
                f"[warm] engine '{method}' built for {self.snapshot_name} "
                f"in {time.perf_counter() - t:.1f}s"
            )
        return self.engines[method]

    def search(self, query: str, method: str = "global") -> str:
        eng = self.engine(method)
        result = asyncio.run(eng.search(query))
        return result.response if hasattr(result, "response") else str(result)


def _read_all_outputs(config: Any) -> dict[str, Optional[pd.DataFrame]]:
    storage_obj = create_storage(config.output_storage)
    table_provider = create_table_provider(config.table_provider, storage=storage_obj)
    reader = DataReader(table_provider)
    out: dict[str, Optional[pd.DataFrame]] = {}
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


def _open_stores(config: Any, names: frozenset[str]) -> dict[str, Any]:
    """method가 요구하는 임베딩 스토어만 연다. global은 빈 set이라 LanceDB 미접근."""
    stores: dict[str, Any] = {}
    if "entity_desc" in names:
        stores["entity_desc"] = get_embedding_store(
            config=config.vector_store, embedding_name=entity_description_embedding
        )
    if "text_unit" in names:
        stores["text_unit"] = get_embedding_store(
            config=config.vector_store, embedding_name=text_unit_text_embedding
        )
    if "full_content" in names:
        stores["full_content"] = get_embedding_store(
            config=config.vector_store, embedding_name=community_full_content_embedding
        )
    return stores


# in-memory RAG 합성 모델 배선용 키. settings.yaml/스냅샷은 안 건드린다.
_RAG_MODEL_ID = "rag_synthesis_model"


def _wire_synthesis_model(config: Any, synthesis_model: str) -> str:
    """global search 합성 모델만 synthesis_model로 in-memory 배선.

    default_completion_model(추출/TOC/Stage B = gpt-4.1-mini)은 안 건드린다.
    default_completion_model을 복제해 deployment만 바꾼 새 항목을 추가하고,
    global_search만 그걸 쓰게 한다. 인덱스 산출물(parquet/LanceDB)은 안 바뀐다.
    돌려주는 값은 global_search가 바인딩하게 될 deployment 이름."""
    base = config.get_completion_model_config(
        config.global_search.completion_model_id
    )
    rag_model = base.model_copy(
        update={
            "model": synthesis_model,
            "azure_deployment_name": synthesis_model,
        }
    )
    config.completion_models[_RAG_MODEL_ID] = rag_model
    config.global_search.completion_model_id = _RAG_MODEL_ID
    return synthesis_model


def load_engine(
    snapshot: Union[str, Path],
    method: str = "global",
    *,
    synthesis_model: Optional[str] = None,
    response_type: Optional[str] = None,
    open_stores: Optional[frozenset[str]] = None,
) -> LoadedEngine:
    """스냅샷 디렉터리 하나를 통째로 로드해 LoadedEngine 번들로 돌려준다.

    snapshot         : 스냅샷 디렉터리(절대 또는 ROOT 상대 경로). run_id 같은
                       제품 키가 아니라 디스크 경로다(레지스트리는 serve.py가 가짐).
    method           : 즉시 빌드할 엔진. 나머지 메서드는 .engine()으로 lazy.
    synthesis_model  : 주면 global search 합성 모델을 그걸로 in-memory 배선.
    response_type    : 엔진 응답 포맷. 생략 시 모듈 기본 RESPONSE_TYPE.
    open_stores      : 열 임베딩 스토어 집합. 생략 시 method에 필요한 것만.
    """
    snapshot_dir = Path(snapshot)
    if not snapshot_dir.is_absolute():
        snapshot_dir = ROOT / snapshot_dir
    if not snapshot_dir.exists():
        raise FileNotFoundError(f"snapshot dir not found: {snapshot_dir}")
    if not (snapshot_dir / "lancedb").exists():
        raise FileNotFoundError(f"lancedb missing in snapshot: {snapshot_dir / 'lancedb'}")

    cli_overrides: dict[str, Any] = {
        "output_storage": {"base_dir": str(snapshot_dir)},
        "vector_store": {"db_uri": str(snapshot_dir / "lancedb")},
    }
    config = load_config(root_dir=ROOT, cli_overrides=cli_overrides)

    bound_synthesis = None
    if synthesis_model:
        bound_synthesis = _wire_synthesis_model(config, synthesis_model)

    t0 = time.perf_counter()
    dfs = _read_all_outputs(config)
    cov = dfs["covariates"]
    print(
        f"[warm] {snapshot_dir.name} parquets loaded in {time.perf_counter() - t0:.1f}s: "
        f"entities={len(dfs['entities'])}, "
        f"communities={len(dfs['communities'])}, "
        f"reports={len(dfs['community_reports'])}, "
        f"text_units={len(dfs['text_units'])}, "
        f"relationships={len(dfs['relationships'])}, "
        f"covariates={'-' if cov is None else len(cov)}"
    )

    want_stores = open_stores if open_stores is not None else _STORES_FOR_METHOD[method]
    t0 = time.perf_counter()
    stores = _open_stores(config, want_stores)
    if stores:
        print(
            f"[warm] {snapshot_dir.name} embedding stores opened in "
            f"{time.perf_counter() - t0:.1f}s: {sorted(stores)}"
        )

    bundle = LoadedEngine(
        snapshot_dir=snapshot_dir,
        config=config,
        dfs=dfs,
        stores=stores,
        response_type=response_type if response_type is not None else RESPONSE_TYPE,
        synthesis_model=bound_synthesis,
    )
    bundle.engine(method)  # 첫 호출이 콜드하지 않게 미리 빌드.
    return bundle


# %% [엔진 빌더] LoadedEngine 컨텍스트만 읽는다 =====================
def _make_local(b: LoadedEngine):
    return get_local_search_engine(
        config=b.config,
        reports=read_indexer_reports(
            b.dfs["community_reports"], b.dfs["communities"], COMMUNITY_LEVEL
        ),
        text_units=read_indexer_text_units(b.dfs["text_units"]),
        entities=read_indexer_entities(
            b.dfs["entities"], b.dfs["communities"], COMMUNITY_LEVEL
        ),
        relationships=read_indexer_relationships(b.dfs["relationships"]),
        covariates={
            "claims": (
                read_indexer_covariates(b.dfs["covariates"])
                if b.dfs["covariates"] is not None
                else []
            )
        },
        description_embedding_store=b.stores["entity_desc"],
        response_type=b.response_type,
        system_prompt=load_search_prompt(b.config.local_search.prompt),
    )


def _make_global(b: LoadedEngine):
    return get_global_search_engine(
        config=b.config,
        reports=read_indexer_reports(
            b.dfs["community_reports"],
            b.dfs["communities"],
            community_level=COMMUNITY_LEVEL,
        ),
        entities=read_indexer_entities(
            b.dfs["entities"], b.dfs["communities"], community_level=COMMUNITY_LEVEL
        ),
        communities=read_indexer_communities(
            b.dfs["communities"], b.dfs["community_reports"]
        ),
        response_type=b.response_type,
        dynamic_community_selection=False,
        map_system_prompt=load_search_prompt(b.config.global_search.map_prompt),
        reduce_system_prompt=load_search_prompt(b.config.global_search.reduce_prompt),
        general_knowledge_inclusion_prompt=load_search_prompt(
            b.config.global_search.knowledge_prompt
        ),
    )


def _make_drift(b: LoadedEngine):
    reports = read_indexer_reports(
        b.dfs["community_reports"], b.dfs["communities"], COMMUNITY_LEVEL
    )
    read_indexer_report_embeddings(reports, b.stores["full_content"])
    return get_drift_search_engine(
        config=b.config,
        reports=reports,
        text_units=read_indexer_text_units(b.dfs["text_units"]),
        entities=read_indexer_entities(
            b.dfs["entities"], b.dfs["communities"], COMMUNITY_LEVEL
        ),
        relationships=read_indexer_relationships(b.dfs["relationships"]),
        description_embedding_store=b.stores["entity_desc"],
        response_type=b.response_type,
        local_system_prompt=load_search_prompt(b.config.drift_search.prompt),
        reduce_system_prompt=load_search_prompt(b.config.drift_search.reduce_prompt),
    )


def _make_basic(b: LoadedEngine):
    return get_basic_search_engine(
        config=b.config,
        text_units=read_indexer_text_units(b.dfs["text_units"]),
        text_unit_embeddings=b.stores["text_unit"],
        response_type=b.response_type,
        system_prompt=load_search_prompt(b.config.basic_search.prompt),
    )


_BUILDERS = {
    "local": _make_local,
    "global": _make_global,
    "drift": _make_drift,
    "basic": _make_basic,
}


# %% [레거시 모듈 API] 기본 스냅샷(repro_run3) lazy 번들 ============
# warm_query를 모듈로 쓰는 기존 코드(exp_warm_compare.py, exp_method_sweep.py)와
# REPL은 config/DFS/ENGINES/_engine/_build_*/ask 를 모듈 전역으로 기대한다.
# import 부수효과는 없애되 이 심볼들은 첫 접근 시 기본 번들을 lazy 로드해 보존한다.
_DEFAULT: Optional[LoadedEngine] = None

# 레거시 호환: 기본 번들은 예전 import-time 동작과 동일하게 3개 스토어를 다 열고
# local 엔진을 즉시 빌드한다(exp_method_sweep가 4개 메서드를 다 sweep하므로).
_DEFAULT_STORES = frozenset({"entity_desc", "text_unit", "full_content"})


def _default_bundle() -> LoadedEngine:
    global _DEFAULT
    if _DEFAULT is None:
        print(f"[init] root     = {ROOT}")
        print(f"[init] snapshot = {SNAPSHOT}")
        _DEFAULT = load_engine(
            SNAPSHOT,
            method="local",
            response_type=RESPONSE_TYPE,
            open_stores=_DEFAULT_STORES,
        )
        print(f"[init] config loaded, vector_store.db_uri = {_DEFAULT.config.vector_store.db_uri}")
        print("[warm] ready. ask('<question>', method='local'|'global'|'drift'|'basic')")
    return _DEFAULT


def _engine(method: str):
    """레거시: 기본 스냅샷 엔진. exp_method_sweep가 wq._engine(method)로 호출."""
    return _default_bundle().engine(method)


def _build_local():
    """레거시: exp_warm_compare가 config 변이 후 wq._build_local()로 재빌드.
    현재 모듈 RESPONSE_TYPE를 반영해 기본 번들 위에서 새 엔진을 만든다."""
    b = _default_bundle()
    b.response_type = RESPONSE_TYPE
    return _make_local(b)


def _build_global():
    b = _default_bundle()
    b.response_type = RESPONSE_TYPE
    return _make_global(b)


def _build_drift():
    b = _default_bundle()
    b.response_type = RESPONSE_TYPE
    return _make_drift(b)


def _build_basic():
    b = _default_bundle()
    b.response_type = RESPONSE_TYPE
    return _make_basic(b)


# PEP 562: 무거운 모듈 전역(config/DFS/ENGINES/스토어)은 첫 접근에 lazy 로드한다.
# 한 번 로드되면 실제 모듈 속성으로 박아 이후 접근은 직접(그리고 in-place 변이 유지).
_LAZY_ATTRS = {
    "config": lambda b: b.config,
    "DFS": lambda b: b.dfs,
    "ENGINES": lambda b: b.engines,
    "ENTITY_DESC_STORE": lambda b: b.stores["entity_desc"],
    "TEXT_UNIT_STORE": lambda b: b.stores["text_unit"],
    "FULL_CONTENT_STORE": lambda b: b.stores["full_content"],
}


def __getattr__(name: str):  # PEP 562 module-level lazy attribute hook
    if name in _LAZY_ATTRS:
        value = _LAZY_ATTRS[name](_default_bundle())
        globals()[name] = value  # 이후 접근은 __getattr__ 안 거치고 직접.
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# %% [셀 3] ask: 질문 바꿔가며 반복 실행 ============================
def ask(query: str, method: str = "local") -> str:
    """질문 한 번 던지고 답 + 소요 시간 출력. 답 문자열 반환(기본 스냅샷)."""
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
    if not SNAPSHOT.exists():
        sys.exit(f"[STOP] snapshot dir not found: {SNAPSHOT}")
    if not (SNAPSHOT / "lancedb").exists():
        sys.exit(f"[STOP] lancedb missing in snapshot: {SNAPSHOT / 'lancedb'}")
    _default_bundle()  # REPL 시작 전에 기본 스냅샷을 미리 로드(예전 동작 유지).
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

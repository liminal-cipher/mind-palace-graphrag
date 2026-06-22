"""litellm 사용량 훅 (서브프로세스 주입용 sitecustomize).

graphrag index / prompt-tune 는 별도 서브프로세스라 부모의 litellm 콜백이 안 잡힌다.
이 디렉터리를 서브프로세스의 PYTHONPATH 앞에 넣으면, 파이썬이 시작 시 sitecustomize 를
자동 import 해서 아래 CustomLogger 를 litellm.callbacks 에 등록한다. 그러면 그 프로세스의
모든 litellm 성공 호출마다 {model, prompt_tokens, completion_tokens} 한 줄(JSONL)을
GRAPHRAG_USAGE_LOG 에 append 한다. 부모는 종료 후 그 파일을 합산한다(orchestrator.usage).

graphrag_llm 은 동기(litellm.completion)와 비동기(litellm.acompletion)를 둘 다 쓴다. 인덱싱
본체(추출 등)는 비동기라, CustomLogger 의 log_success_event(동기)+async_log_success_event
(비동기)를 모두 구현해 litellm.callbacks 에 등록해야 전부 잡힌다(success_callback 만으로는
동기 호출만 잡혀 대부분 누락된다 — e2e 에서 확인).

GRAPHRAG_USAGE_LOG 미설정이면 아무것도 안 한다(무해). litellm 미설치/오류도 조용히 무시.
서브프로세스 본연의 동작(인덱싱)에는 절대 영향 주지 않는다(best-effort 관찰자).
"""
import os


def _install() -> None:
    log_path = os.environ.get("GRAPHRAG_USAGE_LOG")
    if not log_path:
        return
    try:
        import json
        import litellm
        from litellm.integrations.custom_logger import CustomLogger
    except Exception:
        return

    def _extract(kwargs, response_obj) -> dict:
        model = (kwargs or {}).get("model") or getattr(response_obj, "model", "?")
        usage = getattr(response_obj, "usage", None)
        if usage is None and isinstance(response_obj, dict):
            usage = response_obj.get("usage")

        def _g(u, k):
            if u is None:
                return 0
            return u.get(k, 0) if isinstance(u, dict) else (getattr(u, k, 0) or 0)

        return {
            "model": model,
            "prompt_tokens": int(_g(usage, "prompt_tokens") or 0),
            "completion_tokens": int(_g(usage, "completion_tokens") or 0),
        }

    def _write(rec) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass

    class _UsageLogger(CustomLogger):
        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            try:
                _write(_extract(kwargs, response_obj))
            except Exception:
                pass

        async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
            try:
                _write(_extract(kwargs, response_obj))
            except Exception:
                pass

    try:
        litellm.callbacks = list(getattr(litellm, "callbacks", None) or []) + [_UsageLogger()]
    except Exception:
        pass


_install()

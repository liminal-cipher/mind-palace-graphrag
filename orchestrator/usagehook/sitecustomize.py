"""litellm 사용량 훅 (서브프로세스 주입용 sitecustomize).

graphrag index / prompt-tune 는 별도 서브프로세스라 부모의 litellm 콜백이 안 잡힌다.
이 디렉터리를 서브프로세스의 PYTHONPATH 앞에 넣으면, 파이썬이 시작 시 sitecustomize 를
자동 import 해서 아래 콜백을 litellm 에 등록한다. 그러면 그 프로세스의 모든 litellm 성공
호출마다 {model, prompt_tokens, completion_tokens} 한 줄(JSONL)을 GRAPHRAG_USAGE_LOG 에
append 한다. 부모는 서브프로세스 종료 후 그 파일을 합산한다(orchestrator.usage).

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
    except Exception:
        return

    def _cb(kwargs, completion_response, start_time, end_time):
        try:
            model = (kwargs or {}).get("model") or getattr(completion_response, "model", "?")
            usage = getattr(completion_response, "usage", None)
            if usage is None and isinstance(completion_response, dict):
                usage = completion_response.get("usage")

            def _g(u, k):
                if u is None:
                    return 0
                return u.get(k, 0) if isinstance(u, dict) else (getattr(u, k, 0) or 0)

            rec = {
                "model": model,
                "prompt_tokens": int(_g(usage, "prompt_tokens") or 0),
                "completion_tokens": int(_g(usage, "completion_tokens") or 0),
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass  # 관찰자라 본연 동작에 영향 0.

    try:
        cbs = list(getattr(litellm, "success_callback", None) or [])
        cbs.append(_cb)
        litellm.success_callback = cbs
    except Exception:
        pass


_install()

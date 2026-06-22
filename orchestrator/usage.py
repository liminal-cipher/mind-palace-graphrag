"""LLM 사용량·비용 집계 (litellm 기반).

이 시스템의 모든 LLM 호출(graphrag 인덱싱·임베딩, serve 채팅)이 litellm 을 거치므로,
litellm 콜백 하나로 토큰·비용을 잡을 수 있다. 비용은 litellm 내장 단가표(cost_per_token)
로 계산하므로 모델 단가를 따로 관리할 필요가 없다.

사용(같은 프로세스 호출 캡처):
    acc = UsageAccumulator()
    import litellm; litellm.success_callback = [acc.litellm_callback]
    ... LLM 호출 ...
    print(acc.summary())

주의: 인덱싱은 별도 서브프로세스(graphrag index)라 부모 콜백으로는 안 잡힌다. 실측·영속을
하려면 ⓐ 그 서브프로세스에도 콜백 등록(주입), 또는 ⓑ graphrag 로그/cache 파싱이 필요하다.
유저별 영속은 Cosmos `usage` 컨테이너에 record() 결과를 쓰도록 확장한다(후속).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("orchestrator.usage")


def cost_usd(model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> float:
    """litellm 내장 단가표로 (prompt+completion) 비용(USD). 모델 미상/오류면 0.0."""
    try:
        import litellm

        pc, cc = litellm.cost_per_token(
            model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
        return float(pc or 0.0) + float(cc or 0.0)
    except Exception:
        return 0.0


class UsageAccumulator:
    """프로세스 내 LLM 사용량 누적(모델별 토큰·호출수·비용). 벤치마크·집계용."""

    def __init__(self) -> None:
        self.by_model: dict[str, dict] = {}
        self.total_cost: float = 0.0
        self.calls: int = 0

    def record(self, model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> float:
        """한 LLM 호출의 토큰을 더하고 비용을 반환한다."""
        pt, ct = int(prompt_tokens or 0), int(completion_tokens or 0)
        cost = cost_usd(model, pt, ct)
        m = self.by_model.setdefault(
            model, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost": 0.0}
        )
        m["prompt_tokens"] += pt
        m["completion_tokens"] += ct
        m["calls"] += 1
        m["cost"] += cost
        self.total_cost += cost
        self.calls += 1
        return cost

    def litellm_callback(self, kwargs, completion_response, start_time, end_time) -> None:
        """litellm success_callback 시그니처. completion/embedding 응답 usage 에서 토큰 추출."""
        try:
            model = (kwargs or {}).get("model") or getattr(completion_response, "model", "?")
            usage = getattr(completion_response, "usage", None)
            if usage is None and isinstance(completion_response, dict):
                usage = completion_response.get("usage")

            def _g(u, k):
                if u is None:
                    return 0
                return u.get(k, 0) if isinstance(u, dict) else (getattr(u, k, 0) or 0)

            self.record(model, _g(usage, "prompt_tokens"), _g(usage, "completion_tokens"))
        except Exception:
            logger.debug("usage 콜백 파싱 실패", exc_info=True)

    def summary(self) -> dict:
        total_tokens = sum(
            v["prompt_tokens"] + v["completion_tokens"] for v in self.by_model.values()
        )
        return {
            "total_cost_usd": round(self.total_cost, 6),
            "total_tokens": total_tokens,  # 유저 표시는 $ 대신 토큰(Responsible AI).
            "calls": self.calls,
            "by_model": {
                k: {**v, "cost": round(v["cost"], 6)} for k, v in self.by_model.items()
            },
        }


def subprocess_env(base_env: dict, log_path) -> dict:
    """서브프로세스(graphrag index/prompt-tune)에 usage 훅을 주입한 환경 dict 반환.
    PYTHONPATH 앞에 usagehook 디렉터리(sitecustomize) 추가 + GRAPHRAG_USAGE_LOG 설정.
    그러면 그 프로세스의 모든 litellm 호출 토큰이 log_path 에 JSONL 로 쌓인다."""
    import os

    hook_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usagehook")
    env = dict(base_env)
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = hook_dir + ((os.pathsep + prev) if prev else "")
    env["GRAPHRAG_USAGE_LOG"] = str(log_path)
    return env


def aggregate_log(log_path) -> "UsageAccumulator":
    """서브프로세스가 남긴 usage JSONL 을 읽어 합산한 UsageAccumulator 반환.
    파일 없으면 빈 누적기. 깨진 줄은 건너뛴다(관찰 데이터라 best-effort)."""
    import json
    import os

    acc = UsageAccumulator()
    if not log_path or not os.path.isfile(log_path):
        return acc
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    acc.record(
                        r.get("model", "?"),
                        r.get("prompt_tokens", 0),
                        r.get("completion_tokens", 0),
                    )
                except Exception:
                    continue
    except Exception:
        pass
    return acc

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
from sentence_transformers import SentenceTransformer


LOCAL_CRITERION = (
    "A question asking about one or a few specific entities, events, people, "
    "places, terms, tools, institutions, roles, causes, results, differences, "
    "or relations. Use local search when the answer should be grounded in "
    "nearby entities, relationships, and source text."
)

GLOBAL_CRITERION = (
    "A broad question asking for the whole document, unit, topic, overall flow, "
    "summary, theme, structure, synthesis, or long-term change. Use global "
    "search when the answer should be based on community reports and high-level "
    "summaries."
)

# Korean cue words are written as unicode escapes so this file remains ASCII-safe
# across Windows consoles and Azure Linux deployments.
GLOBAL_CUE_PATTERN = re.compile(
    "("
    "\uc804\uccb4|"  # whole
    "\uc804\ubc18|"  # overall
    "\uc694\uc57d|"  # summary
    "\uc815\ub9ac|"  # organize
    "\ud750\ub984|"  # flow
    "\ud070\\s*\ud750\ub984|"
    "\ud575\uc2ec|"  # core
    "\uc8fc\uc81c|"  # theme
    "\uad6c\uc870|"  # structure
    "\uac1c\uad04|"  # overview
    "\uc885\ud569|"  # synthesis
    "\uc790\ub8cc\\s*\uc804\uccb4|"
    "\ubb38\uc11c\\s*\uc804\uccb4|"
    "\ub2e8\uc6d0\\s*\uc804\uccb4|"
    "\ubcc0\ud654\\s*\uacfc\uc815"
    ")"
)

LOCAL_COMPARE_PATTERN = re.compile(
    "("
    "\ucc28\uc774|"  # difference
    "\ube44\uad50|"  # comparison
    "\uad00\uacc4|"  # relation
    "\uacf5\ud1b5\uc810|"
    "\ub2e4\ub978\\s*\uc810|"
    "\uad6c\ubd84"
    ")"
)

GENERIC_ENTITY_TITLES = {
    "\uc870\uc120",  # Joseon
    "\uace0\ub824",  # Goryeo
    "\uba85",  # Ming
    "\uccad",  # Qing
    "\uc77c\ubcf8",  # Japan
    "\uc911\uad6d",  # China
    "\uc655",  # king
    "\uad6d\uac00",  # state
    "\uc815\uce58",  # politics
    "\uc0ac\ud68c",  # society
    "\uacbd\uc81c",  # economy
    "\ubb38\ud654",  # culture
}


@dataclass
class RouteResult:
    mode: str
    raw_mode: str
    scores: dict[str, float]
    gap: float
    confidence: str
    entity_hits: list[str]
    global_cue: bool
    local_compare_cue: bool
    reason: str


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def _find_entity_hits(
    question: str,
    entity_titles: Iterable[str] | None,
    limit: int = 8,
) -> list[str]:
    if not entity_titles:
        return []

    hits: list[str] = []
    seen: set[str] = set()
    for title in entity_titles:
        title = str(title).strip()
        if len(title) < 2 or title in GENERIC_ENTITY_TITLES or title in seen:
            continue
        if title in question:
            hits.append(title)
            seen.add(title)
        if len(hits) >= limit:
            break
    return hits


class BGERouter:
    """BGE-M3 based local/global router.

    BGE-M3 is used only to choose the search family. It does not generate
    answers and it does not select community reports for global search.
    """

    def __init__(self, model_path: str | None = None, device: str | None = None):
        self.model_path = model_path or os.getenv("BGE_MODEL_PATH", "BAAI/bge-m3")
        self.device = device or os.getenv("BGE_DEVICE", "cpu")
        self.model = SentenceTransformer(self.model_path, device=self.device)
        self.criteria = {
            "local": LOCAL_CRITERION,
            "global": GLOBAL_CRITERION,
        }
        criterion_texts = [f"{name}: {text}" for name, text in self.criteria.items()]
        self.criterion_embeddings = np.asarray(
            self.model.encode(criterion_texts, normalize_embeddings=True)
        )

    def route(
        self,
        question: str,
        entity_titles: Iterable[str] | None = None,
    ) -> RouteResult:
        q_emb = np.asarray(self.model.encode([question], normalize_embeddings=True))[0]
        names = list(self.criteria)
        scores = {
            name: _cosine(q_emb, self.criterion_embeddings[i])
            for i, name in enumerate(names)
        }
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        raw_mode = ranked[0][0]
        gap = ranked[0][1] - ranked[1][1]

        entity_hits = _find_entity_hits(question, entity_titles)
        has_global_cue = bool(GLOBAL_CUE_PATTERN.search(question))
        has_local_compare = bool(LOCAL_COMPARE_PATTERN.search(question))

        mode = raw_mode
        reason = "BGE criterion similarity"

        if has_global_cue and not entity_hits:
            mode = "global"
            reason = "broad/global cue without a direct entity match"
        elif has_global_cue and entity_hits and not has_local_compare:
            mode = "global"
            reason = "broad/global cue dominates the entity mention"
        elif entity_hits:
            mode = "local"
            reason = "direct GraphRAG entity match in the question"
        elif scores["global"] - scores["local"] >= 0.05:
            mode = "global"
            reason = "global score is sufficiently higher than local"
        else:
            mode = "basic"
            reason = "no strong local/global signal, defaulting to basic"

        confidence = "clear" if mode != raw_mode or gap >= 0.04 else "ambiguous"
        return RouteResult(
            mode=mode,
            raw_mode=raw_mode,
            scores={k: round(v, 6) for k, v in scores.items()},
            gap=round(float(gap), 6),
            confidence=confidence,
            entity_hits=entity_hits,
            global_cue=has_global_cue,
            local_compare_cue=has_local_compare,
            reason=reason,
        )

    def route_dict(
        self,
        question: str,
        entity_titles: Iterable[str] | None = None,
    ) -> dict:
        return asdict(self.route(question, entity_titles))


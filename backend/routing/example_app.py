from __future__ import annotations

import os
from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel

from backend.routing.graphrag_search_client import GraphRAGSearchClient
from backend.routing.routing_bge import BGERouter


class QuestionRequest(BaseModel):
    question: str


class QuestionResponse(BaseModel):
    question: str
    route: dict
    search: dict | None = None


app = FastAPI(title="GraphRAG BGE Router Example")


@lru_cache(maxsize=1)
def get_search_client() -> GraphRAGSearchClient:
    return GraphRAGSearchClient(os.getenv("GRAPHRAG_REPO_ROOT"))


@lru_cache(maxsize=1)
def get_router() -> BGERouter:
    return BGERouter(
        model_path=os.getenv("BGE_MODEL_PATH"),
        device=os.getenv("BGE_DEVICE", "cpu"),
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/route", response_model=QuestionResponse)
def route_only(req: QuestionRequest) -> QuestionResponse:
    search_client = get_search_client()
    router = get_router()
    route = router.route_dict(req.question, search_client.entity_titles())
    return QuestionResponse(question=req.question, route=route)


@app.post("/query", response_model=QuestionResponse)
def query(req: QuestionRequest) -> QuestionResponse:
    search_client = get_search_client()
    router = get_router()
    route = router.route_dict(req.question, search_client.entity_titles())
    search = search_client.search(req.question, route["mode"])
    return QuestionResponse(question=req.question, route=route, search=search)


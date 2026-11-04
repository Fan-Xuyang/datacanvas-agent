import asyncio
import json

import httpx

from app.reranker import rerank


def test_remote_reranker_orders_only_recalled_candidates(monkeypatch):
    monkeypatch.setenv("RERANKER_URL", "https://reranker.test/rerank")
    monkeypatch.setenv("RERANKER_MODEL", "cross-encoder-v1")
    monkeypatch.setenv("RERANKER_API_KEY", "test-token")

    def handle(request):
        payload = json.loads(request.content)
        assert payload["query"] == "材料耐蚀性能"
        assert payload["documents"] == ["片段甲", "片段乙"]
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={"results": [{"index": 1, "relevance_score": 0.97}]},
        )

    candidates = [
        (0.1, ("a", "d1", "file.md", 1, "片段甲", None)),
        (0.2, ("b", "d1", "file.md", 1, "片段乙", None)),
    ]
    result = asyncio.run(
        rerank(
            "材料耐蚀性能",
            candidates,
            limit=1,
            transport=httpx.MockTransport(handle),
        )
    )
    assert result == [(0.97, ("b", "d1", "file.md", 1, "片段乙", None))]


def test_remote_reranker_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("RERANKER_URL", raising=False)
    assert asyncio.run(
        rerank("query", [(0.1, ("a", "d1", "file.md", 1, "text", None))])
    ) is None

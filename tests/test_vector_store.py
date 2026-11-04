import asyncio
import json

import httpx

from app.vector_store import QdrantIndex


def test_qdrant_upsert_search_and_delete_are_tenant_scoped(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"status": {"error": "missing"}})
        if request.url.path.endswith("/points/search"):
            payload = json.loads(request.content)
            must = payload["filter"]["must"]
            assert {item["key"] for item in must} == {
                "tenant_id",
                "embedding_model",
            }
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"payload": {"chunk_id": "a" * 32}, "score": 0.91}
                    ]
                },
            )
        return httpx.Response(200, json={"result": {"status": "ok"}})

    monkeypatch.setenv("QDRANT_URL", "http://qdrant.test")
    index = QdrantIndex(transport=httpx.MockTransport(handle))
    point_id = "a" * 32
    vector = [0.1, 0.2, 0.3]

    async def exercise():
        assert await index.upsert(
            [{"id": point_id, "vector": vector}], "embed-v1", "tenant-a"
        )
        assert await index.search(vector, "embed-v1", "tenant-a") == [
            (point_id, 0.91)
        ]
        await index.delete([point_id], "embed-v1", len(vector))

    asyncio.run(exercise())
    point_write = next(call for call in calls if call.method == "PUT" and "/points?" in str(call.url))
    payload = json.loads(point_write.content)["points"][0]
    assert payload["payload"]["tenant_id"] == "tenant-a"
    assert payload["payload"]["chunk_id"] == point_id
    assert any(call.url.path.endswith("/points/delete") for call in calls)


def test_qdrant_disabled_keeps_local_vector_mode(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    assert QdrantIndex().enabled is False

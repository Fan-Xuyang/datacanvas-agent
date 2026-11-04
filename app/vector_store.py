"""Optional Qdrant vector index for tenant-scoped RAG retrieval."""

import hashlib
import os
import re
import uuid

import httpx


class QdrantIndex:
    def __init__(self, transport=None):
        self.url = os.getenv("QDRANT_URL", "").rstrip("/")
        self.api_key = os.getenv("QDRANT_API_KEY", "")
        raw_prefix = os.getenv("QDRANT_COLLECTION_PREFIX", "datacanvas")
        self.prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_prefix).strip("_") or "datacanvas"
        self.transport = transport

    @property
    def enabled(self):
        return bool(self.url)

    def collection(self, model, dimensions):
        suffix = hashlib.sha1(model.encode("utf-8")).hexdigest()[:10]
        return f"{self.prefix}_{suffix}_{dimensions}"

    def _headers(self):
        return {"api-key": self.api_key} if self.api_key else {}

    async def _client(self):
        return httpx.AsyncClient(
            base_url=self.url,
            headers=self._headers(),
            timeout=httpx.Timeout(12.0),
            transport=self.transport,
        )

    async def _ensure_collection(self, client, name, dimensions):
        response = await client.get(f"/collections/{name}")
        if response.status_code == 200:
            return
        if response.status_code != 404:
            response.raise_for_status()
        response = await client.put(
            f"/collections/{name}",
            json={"vectors": {"size": dimensions, "distance": "Cosine"}},
        )
        # Another worker may have created the collection concurrently.
        if response.status_code not in (200, 201, 409):
            response.raise_for_status()

    async def upsert(self, points, model, tenant_id):
        if not self.enabled or not points:
            return False
        name = self.collection(model, len(points[0]["vector"]))
        async with await self._client() as client:
            await self._ensure_collection(client, name, len(points[0]["vector"]))
            response = await client.put(
                f"/collections/{name}/points?wait=true",
                json={
                    "points": [
                        {
                            "id": str(uuid.UUID(hex=point["id"])),
                            "vector": point["vector"],
                            "payload": {
                                "chunk_id": point["id"],
                                "tenant_id": tenant_id,
                                "embedding_model": model,
                            },
                        }
                        for point in points
                    ]
                },
            )
            response.raise_for_status()
        return True

    async def search(self, vector, model, tenant_id, limit=40):
        if not self.enabled:
            return None
        name = self.collection(model, len(vector))
        async with await self._client() as client:
            response = await client.post(
                f"/collections/{name}/points/search",
                json={
                    "vector": vector,
                    "limit": limit,
                    "with_payload": ["chunk_id"],
                    "filter": {
                        "must": [
                            {"key": "tenant_id", "match": {"value": tenant_id}},
                            {"key": "embedding_model", "match": {"value": model}},
                        ]
                    },
                },
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            rows = response.json().get("result", [])
        return [
            (row.get("payload", {}).get("chunk_id"), float(row.get("score", 0)))
            for row in rows
            if row.get("payload", {}).get("chunk_id")
        ]

    async def delete(self, chunk_ids, model, dimensions):
        if not self.enabled or not chunk_ids or not model or not dimensions:
            return
        name = self.collection(model, dimensions)
        async with await self._client() as client:
            response = await client.post(
                f"/collections/{name}/points/delete?wait=true",
                json={"points": [str(uuid.UUID(hex=item)) for item in chunk_ids]},
            )
            if response.status_code != 404:
                response.raise_for_status()

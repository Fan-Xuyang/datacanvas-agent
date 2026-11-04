"""Optional cross-encoder reranking through a Cohere-compatible endpoint."""

import os

import httpx


async def rerank(query, candidates, limit=5, transport=None):
    endpoint = os.getenv("RERANKER_URL", "").strip()
    model = os.getenv("RERANKER_MODEL", "").strip()
    if not endpoint or not model or not candidates:
        return None
    headers = {}
    key = os.getenv("RERANKER_API_KEY", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0), transport=transport
    ) as client:
        response = await client.post(
            endpoint,
            headers=headers,
            json={
                "model": model,
                "query": query,
                "documents": [row[1][4] for row in candidates],
                "top_n": min(limit, len(candidates)),
                "return_documents": False,
            },
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    ranked = []
    for item in results:
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(candidates):
            ranked.append((float(item.get("relevance_score", 0)), candidates[index][1]))
    return ranked[:limit]

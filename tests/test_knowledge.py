import asyncio

from app.knowledge import KnowledgeBase
from shared.store import Store


def test_markdown_ingestion_hybrid_search_and_deduplication(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(tmp_path / "state.sqlite3")
    knowledge = KnowledgeBase(store)
    raw = (
        "# 材料检验标准\n\n"
        "耐蚀合金的屈服强度应依据批次检验报告确认。\n"
        "发生退货时应将退货明细单独核对，不计入正向销售额。"
    ).encode()

    added = asyncio.run(knowledge.add_document("material-standard.md", raw))
    duplicate = asyncio.run(knowledge.add_document("another-name.md", raw))
    results = asyncio.run(knowledge.search("耐蚀合金的屈服强度是多少", limit=3))

    assert added["chunks"] == 1
    assert not added["duplicate"]
    assert duplicate["duplicate"]
    assert results
    assert results[0]["filename"] == "material-standard.md"
    assert "屈服强度" in results[0]["content"]

    answer = asyncio.run(knowledge.answer("屈服强度的验收依据是什么"))
    assert "未配置生成模型" in answer["answer"]
    assert answer["citations"][0]["id"] == results[0]["id"]


def test_knowledge_document_delete_is_tenant_scoped(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    knowledge = KnowledgeBase(store)
    document = asyncio.run(
        knowledge.add_document("standard.txt", "检验前先核对材料批次。".encode())
    )

    assert not knowledge.delete_document(document["id"], tenant_id="other")
    assert len(knowledge.documents()) == 1
    assert knowledge.delete_document(document["id"])
    assert knowledge.documents() == []

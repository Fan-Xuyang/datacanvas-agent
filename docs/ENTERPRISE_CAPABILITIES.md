# DataCanvas AI Agent 工程能力

## AI 应用与模型服务

- OpenAI-compatible Chat Completions 与 Embeddings 接口，可配置 DeepSeek 或其他兼容服务。
- Pydantic 结构化响应校验、受控修复、token 与延迟记录；单实例最多并行执行两个后台任务。
- Agent Harness 使用类型化工具注册、状态检查点、取消与恢复、持久化事件和 SSE 实时轨迹。
- SQL 工具仅运行单条只读查询，经过 SQLGlot AST 校验，并在独立 DuckDB 子进程中限制资源和结果规模。
- Agent Skills 从版本化 `skills/*/SKILL.md` 加载业务约束；MCP 提供可发现的工具、资源、Prompt 和出站只读工具调用。

## RAG 检索与评测

文档链路为 PDF/TXT/Markdown/CSV 解析、按页切分、可选 OCR、Embedding、FTS5 BM25 与 Qdrant 召回、RRF 融合、词项覆盖重排或可选 Cross-Encoder 重排、带来源引用的回答。引用 ID 会根据实际检索证据校验。

Qdrant 集合按 Embedding 模型与向量维度隔离，检索和删除均按租户过滤。没有配置外部 Embedding / Qdrant 时仍可通过全文检索运行；本地向量检索也可直接使用 SQLite 中的 Embedding。

`POST /api/evaluations/rag` 接受人工标注的相关 Chunk ID，返回 Recall@k、Precision@k 与 MRR。`docs/EVALUATION.md` 区分了规则分析回归、模型调用和检索评测的口径。

## 数据工程、安全与运行观测

- CSV/XLSX 导入、schema 推断、SHA-256 来源血缘、空值/唯一度/重复行质量剖析。
- SQL 指标规划、图表结果、CSV/Markdown 报告、模型调用记录及任务轨迹。
- Bearer 身份、admin/analyst/viewer 角色、租户隔离、管理员审计、任务并发限制与只读数据工具。
- 健康接口、`/api/metrics`、SSE 事件流、RAG 与 SQL 离线评测，以及 GitHub Actions 自动检查。

## 本地运行和容器演示

Windows 本地环境：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

浏览器打开 <http://127.0.0.1:8201>。容器演示使用 Docker Compose，包含 Web 应用、持久化数据卷和 Qdrant 向量服务。模型、OCR、Embedding、向量库和重排服务通过 `.env` 配置；密钥不进入 Git。

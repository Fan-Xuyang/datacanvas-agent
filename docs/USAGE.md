# DataCanvas 本地使用与工程说明

## 本地运行

首次启动时，应用将 `examples/uci_online_retail_sample.csv` 导入本地 DuckDB。可以试问：

1. “按国家汇总销售额”
2. “按月份查看销售额趋势”
3. “按商品统计商品数量”
4. “按国家统计订单数”或“按国家统计不同客户数”
5. “筛选国家=France，按月份汇总销售额”

报告会展示实际 SQL、结果表、数据集名称与内容校验值，结果表可下载为 CSV。支持销售额、商品数量、平均单价、不同发票数、不同客户数和原始记录数；国家、月份和商品编码可精确筛选。销售额口径为筛选后交易的数量乘英镑单价之和；样本排除了取消单、退货及零价明细，没有成本字段。

## 企业知识库

在工作台“企业知识库”区域导入 PDF / TXT / Markdown / CSV，可检索原文或查看有来源引用的回答。每个命中项保留文档名和页码；删除文档会一并移除全文索引和片段。无模型配置时页面明确显示检索片段，不生成答案。

在 `.env` 设置 `AI_API_KEY`、`AI_BASE_URL` 和 `AI_MODEL` 可启用回答生成。DeepSeek 示例使用 `https://api.deepseek.com/v1` 与 `deepseek-chat`。Embedding 需独立配置 `AI_EMBEDDING_API_KEY`、`AI_EMBEDDING_BASE_URL`、`AI_EMBEDDING_MODEL`；有 embedding 时新导入文档会保存向量，并与 FTS5 结果做 reciprocal-rank fusion。旧文档需要重新导入以生成向量。向量按本地 SQLite 保存，适合本地与小规模样本；大规模生产还需接入 Qdrant 等专用向量服务。

配置 Embedding 后，还可设置 `QDRANT_URL`、`QDRANT_API_KEY` 和可选的 `QDRANT_COLLECTION_PREFIX` 启用 Qdrant 向量索引。系统按嵌入模型和维度创建集合，写入仅含 chunk ID、租户 ID 和模型名的 payload；原文仍由本地知识库按租户过滤读取。Qdrant 不可用时检索请求会返回服务错误，避免静默切换到全量扫描。未配置 Qdrant 时使用本地 SQLite 向量余弦检索。

可选语义重排使用兼容 Cohere Rerank 请求格式的服务：设置 `RERANKER_URL`、`RERANKER_MODEL` 和服务要求时使用的 `RERANKER_API_KEY`。重排只接收混合检索召回的候选片段，不取代租户隔离或引用来源校验。没有配置重排服务时使用内置词项覆盖重排。

扫描版 PDF 可通过 `OCR_ENABLED=true` 启用 OCR。运行机器需要安装 Tesseract，并安装 `TESSERACT_LANG` 指定的语言包；默认语言为英文和简体中文。容器镜像内已包含对应 OCR 引擎和语言包。本机 Windows 可安装 Tesseract 后设置 `TESSERACT_CMD` 指向其可执行文件。

## 共享部署的身份与租户

本地默认单用户。共享实例需启用 `DATACANVAS_AUTH_REQUIRED=true`，并把 `DATACANVAS_TOKENS` 配成 bearer token 到 `tenant_id`、`role`、`sub` 的映射。角色支持 `admin`、`analyst`、`viewer`；viewer 为只读，只有 admin 能查看 `/api/audit`。数据集、任务、知识文档和审计查询按 token 关联的 tenant 隔离。Token 只放入被忽略的 `.env` 或密钥管理服务，不要提交到 Git。

内置 bearer 验证是单实例运行时的基础保护，企业身份联邦应由 OIDC/SSO 网关负责；上线时还需启用 HTTPS、限制网络入口并使用集中密钥管理。

## 结构与限制

| 模块 | 说明 |
| --- | --- |
| `app/data.py` | CSV / XLSX 导入、列名规范化、SQL AST 校验与查询子进程调用 |
| `app/query_worker.py` | 受内存、线程、时间和行数限制的只读 DuckDB 查询 |
| `app/planning.py` | 无模型的有限规则规划器；按 schema 将“国家”映射到 `country`、商品映射到 `description` |
| `app/agent.py` | 规划、执行、字段校验和证据报告状态机 |
| `shared/store.py` | 任务状态与事件持久化 |
| `shared/api.py` | 后台执行、取消、恢复与 SSE 事件重放 |
| `frontend/src/App.tsx` | 查询输入、图表渲染、状态轨迹与报告展示 |

应用最多导入 20,000 行，规则规划器每次只支持一个指标和一个分组维度。复杂分析可配置兼容模型接口；模型输出仍受结构化字段和只读 SQL 校验约束。仓库中的固定测试夹具用于可重复验证，不会作为默认数据载入。

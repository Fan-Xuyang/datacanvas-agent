# DataCanvas 能力范围与边界

这里记录的是当前代码实际提供的能力。运行在本地的完整 Agent 应用不等于已经具备多副本、高可用、企业 SSO 的生产平台；未验证的能力不标记为已完成。

| 技能域 | 当前可运行能力 | 仍需补齐的生产能力 |
| --- | --- | --- |
| LLM 接入 | OpenAI-compatible chat API；可配置 DeepSeek；结构化 JSON 输出、单次修复、token 与延迟记录 | Provider 路由、熔断/预算、成本计价、密钥托管、模型级并发控制 |
| RAG | PDF/TXT/Markdown/CSV 解析，分块、租户过滤、FTS5 BM25、可选向量召回、RRF、轻量词项重排、引用 ID 校验；提供按人工标注 Chunk ID 评测 Recall@k/Precision@k/MRR 的 API | Qdrant/pgvector 持久向量服务、Cross-Encoder 重排、OCR、增量更新、经业务审核维护的黄金集 |
| Agent Harness | Pydantic 参数校验的工具注册、超时、只读 SQL、SQL AST 校验、持久化事件、重启恢复 | 独立工作队列、全局预算、工具幂等键、重试/退避、隔离沙箱、审批策略 DSL |
| Agent 工作流 | 知识检索 → 规划 → 工具执行 → 结果验证 → 报告；步骤有事件记录 | 角色化多 Agent 并行/交接、可视化 DAG、检查点版本迁移 |
| Agent Skills | `skills/*/SKILL.md` 版本化业务规范，按关键词选择，写入任务事件 | 完整 frontmatter/schema 校验、Skill 测试集、远端分发和权限签名 |
| MCP | 官方 Python SDK 的 MCP Server，提供数据集、只读分析、知识搜索/问答工具和资源/Prompt；stdio 与 Streamable HTTP；可配置出站 Client，发现并调用声明只读的工具 | 持久连接池、OAuth 委托授权、写工具审批/幂等、MCP 远端工具的模型自主规划 |
| 数据工程 | CSV/XLSX 导入，schema 推断、文件 SHA-256、来源血缘、空值/唯一度/重复行剖析 | 可复用 ETL DAG、Schema 演进、质量规则管理、告警、增量 CDC |
| Text-to-SQL | 结构化计划、业务指标词典、SQLGlot 只读约束、DuckDB 隔离子进程和数值回归 | 多表语义层、列级权限、复杂查询计划、真实业务指标黄金集 |
| 大数据 | 本地 DuckDB 路径适合中小文件；未伪称分布式处理 | Hadoop/Spark/Flink 批流任务、元数据目录和集群部署 |
| 企业安全 | Bearer token → 角色/租户映射；任务、数据集、知识和审计按租户隔离；viewer 只读 | OIDC/SSO、密钥管理、TLS/网络策略、行列级 ACL、审计防篡改、渗透测试 |
| 评测与观测 | 固定 SQL 结果与拒绝用例基准、人工标注 RAG 检索评测 API、运行事件流、token/延迟计数、租户审计、数据质量概览 | 持续维护的 RAG/Agent 黄金集、OpenTelemetry traces、Prometheus 告警、线上漂移评估 |
| 部署与恢复 | Windows 本地启动、SQLite + DuckDB、健康接口、进程重启恢复 | Docker/Compose、PostgreSQL、Redis 队列、对象存储、备份恢复演练、多副本 HA |

## 已覆盖的端到端路径

1. 使用开放 UCI Online Retail 数据或导入本地 CSV/XLSX；查看 schema、质量提示和来源摘要。
2. 上传业务文档并按租户检索；回答需带被校验的文档片段引用。
3. Agent 根据 schema、指标口径、命中的 Skill 和知识证据生成结构化计划。
4. SQL 工具只接受数据集 ID 与 SQL；服务端解析器限制表、语句类型、函数、执行时长、内存和结果行数。
5. 每个阶段保存状态和事件；崩溃后任务可恢复，管理员能查询本租户审计记录和运行统计。
6. MCP Host 可发现 DataCanvas 的工具、资源和 Prompt，并通过 stdio 或 Streamable HTTP 调用。

## 配置共享访问

`DATACANVAS_AUTH_REQUIRED=true` 后，`DATACANVAS_TOKENS` 使用 JSON 字典配置 bearer token 对应的 `tenant_id`、`role`、`sub`。角色为 `admin`、`analyst`、`viewer`。本地单用户默认模式仍可离线运行。共享部署必须在 TLS 与可信网络边界后运行，并使用组织认可的身份系统和密钥托管。

## 下一步工程顺序

1. 先完成可复现的 RAG/Agent 黄金评测和工具权限/超时测试。
2. 将状态库迁至 PostgreSQL、任务执行迁至 Redis 队列，并加入容器化部署与备份恢复。
3. 增加 MCP 持久连接池、审批/幂等策略和结构化多 Agent DAG。
4. 接入 Qdrant 或 pgvector 与专用 reranker，再通过业务黄金集验证召回和引用正确性。
5. 接入 OIDC、OpenTelemetry、Prometheus 告警以及 Spark/Hadoop 连接器。

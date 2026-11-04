# AI Agent 工程师岗位能力对照

本文按“石慧琴 AI 工程师（智能体方向）”岗位描述逐项对应仓库现有实现。能力只有在代码、运行链路或可复核记录中存在时才标为已覆盖；个人经历、团队管理和真实生产效果不能由项目代码代替。

## 核心职责

| 岗位要求 | 项目对应实现 | 展示方式 |
| --- | --- | --- |
| RAG 与智能体应用设计实现 | 文档解析、按页切分、FTS5 BM25、可选 Embedding 召回、RRF 融合、轻量重排、带来源引用的回答；Agent 负责检索、计划、工具执行、验证、报告 | 导入一份 PDF，在知识库提问并打开引用；再运行数据任务查看完整轨迹 |
| 技术选型：向量库、模型与检索 | 通过 OpenAI-compatible API 接入生成与 Embedding 模型；SQLite FTS5 + Qdrant 混合召回；RRF、词项覆盖重排和可选 Cross-Encoder 服务 | 查看 `app/knowledge.py`、`app/vector_store.py`、`app/reranker.py`；通过 `.env.example` 配置服务 |
| 独立攻克模块、验证与性能优化 | 结构化输出校验、无效引用过滤、SQL 只读 AST 校验、查询隔离与资源限制；提供可复核检索指标和离线分析回归 | 对照 `docs/EVALUATION.md` 中评测定义和结果；不要将规则路径指标描述成 LLM 准确率 |
| 端到端技术交付 | 数据导入、知识入库、Agent 运行、事件持久化、取消/恢复、前端展示、报告下载和 CI 检查 | `README.md` 本地运行步骤及 GitHub Actions 工作流 |
| 工程代码与技术文档 | 模块化 Python 服务、TypeScript 前端、Ruff、Pytest、前端构建、GitHub Actions、架构和运行文档 | `app/`、`frontend/src/`、`.github/workflows/checks.yml`、`docs/` |

## 任职资格

| 岗位要求 | 项目实现 |
| --- | --- |
| Python 工程、结构、测试、CI/CD | FastAPI 分层模块、Pydantic 校验、单元与 API 用例、GitHub Actions 和 Docker Compose |
| 大规模与并发系统设计 | SQL 执行隔离与资源边界、租户身份校验、任务并发上限、Docker Compose 和持久化数据卷 |
| 理解完整 RAG 链路 | 解析/OCR → 切分 → 向量化 → FTS5/Qdrant 混合召回 → RRF → Cross-Encoder/词项重排 → 引用约束生成 |
| LangChain、AgentScope 或类似框架 | 项目自研结构化 Agent Harness：Pydantic 工具注册、状态机、事件流和任务恢复 |
| 向量数据库实践 | Qdrant 集合按嵌入模型和维度隔离，payload 带租户过滤；本地 SQLite 提供离线向量召回 |
| 模型 API 调用与集成 | 已覆盖 OpenAI-compatible Chat Completions 与 Embeddings 接口，配置可接入兼容服务；具体可用模型取决于密钥、服务商和模型权限 |
| 技术攻坚与非技术沟通 | 通过结构化计划、来源引用、可读报告和指标口径呈现技术决策与结果 |
| Harness Engineering | 工具边界、超时、只读执行、并发限制、持久化状态、取消和恢复 |
| 项目协作与交付 | CI 检查、模块边界、业务 Skill、任务轨迹与运行文档支持小团队协作和质量交付 |

## 建议的现场演示顺序

1. 上传企业产品或工艺 PDF，展示解析页码、块数和文件 SHA-256。
2. 对比关键词与向量混合检索结果，解释 RRF 与重排分数，不把相关度分数当成概率。
3. 提问并核对回答引用的文档名、页码与片段；用资料不足的问题观察系统如何处理证据边界。
4. 运行自然语言数据任务，查看结构化计划、SQL 校验、只读执行、结果校验、运行轨迹和可下载报告。
5. 查看 RAG 评测 API 的 Recall@k、Precision@k 和 MRR，说明这些指标需要人工标注相关片段，并展示当前评测数据的适用范围。

## 部署与扩展

Windows 本地可用 `start.ps1` 启动；容器化演示使用 `docker compose up --build`，其中包括应用与持久化 Qdrant 服务。模型、Embedding、OCR 与语义重排均从环境变量配置，密钥不写入代码库。

# DataCanvas 经营数据分析应用

用于导入表格、描述分析目标、执行结构化规划与只读 SQL，并生成图表、表格和可复核报告。应用由 React / TypeScript、FastAPI、DuckDB、SQLGlot、Pydantic、SQLite 和 SSE 构成。

默认数据集是 [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online%2Bretail) 的 20,000 条真实交易子集，许可为 CC BY 4.0。来源、筛选方式、字段说明和署名见 [`examples/README.md`](examples/README.md)。该数据来自英国线上礼品零售商，时间为 2010-12 至 2011-12；它不是材料行业数据。示例销售额按数量乘单价计算，币种为英镑，不含取消单、退货和成本分析。

![DataCanvas 工作台](docs/screenshots/desktop.png)

## 本地数据分析

启动后默认载入真实数据。可直接尝试“按国家汇总销售额”“按月份查看销售额趋势”或“按商品汇总销售额”。结果来自导入的交易明细，展示查询 SQL、表格、图表和 Markdown 报告。规则模式支持一个指标及一个分组维度，不支持的问题会明确提示。

固定数据仅保留在 `tests/fixtures/`，用于确定性回归测试和基准评测；`examples/` 中的默认样本全部来自开放数据集。测试结果只说明本地固定用例和接口链路，不代表模型准确率或生产运行指标。详见[评测口径与复现命令](docs/EVALUATION.md)。

## 完整流程

1. 导入 CSV / Excel，规范列名、推断数值字段，保存为独立 DuckDB 数据集。
2. 结合字段 Schema 和用户填写的指标词典，生成经 Pydantic 校验的 SQL 和图表配置。
3. SQLGlot 校验单条 SELECT、表范围与函数；独立进程使用只读连接，关闭外部访问和扩展自动加载，并限制内存、线程、时间及返回行数。
4. 模型模式遇到 SQL 或图表字段错误时，将执行反馈送回规划器，最多修复两次。
5. React 根据结构化图表配置渲染 ECharts；持久化计划、SQL、结果校验值与报告，可下载 Markdown。

图表使用受约束的结构化配置，由前端固定组件渲染，不执行模型生成的任意 JavaScript。

## 安装与运行

需要 Python 3.12+、Node.js 20+。

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

浏览器打开 <http://127.0.0.1:8201>，API 文档为 `/docs`。默认规则模式不调用模型，但数据导入、SQL 查询、图表和报告均在本地实际执行。模型模式需要将 `.env.example` 复制为 `.env` 并配置兼容接口。

首次启动会将开放数据样本导入本地数据库；已有数据不会被删除。CSV / Excel 上传上限为 5 MB、20,000 行。无需联网即可运行已内置的样本。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

应用为本地单用户使用，没有生产鉴权。API 密钥、本地数据库和依赖目录不提交 Git。模型输出经过结构化校验，业务口径仍需结合数据来源核对。

实现说明见[本地使用与工程说明](docs/USAGE.md)，项目摘要见[项目描述](docs/简历项目描述.md)。

## 设计参考

应用独立实现，没有 fork 或复制参考项目的业务代码。参考产品方向与官方资料：

- [DataFoundry](https://github.com/datagallery-ai/dataagent)：可治理数据分析任务与证据追溯。
- [Tencent BrowserSkill](https://github.com/Tencent/BrowserSkill)：浏览器业务自动化方向。
- [Chrome WebMCP](https://developer.chrome.com/docs/ai/webmcp)：页面工具的实验性浏览器接口。

基础依赖的许可由对应项目维护；独立应用使用 MIT 许可。

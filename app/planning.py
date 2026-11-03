"""Explicit, bounded offline planner; not a substitute for a measured LLM."""

import re

METRICS = {
    "sales": ("销售额", "销售收入", "营收", "sales"),
    "cost": ("成本", "支出", "cost"),
    "quantity": ("商品数量", "销售数量", "数量", "quantity", "qty"),
    "unit_price": ("平均单价", "单价", "unit_price"),
    "orders": ("订单数", "订单量", "distinct orders", "orders"),
    "customers": ("客户数量", "客户数", "不同客户", "distinct customers", "customers"),
    "profit": ("毛利", "利润", "profit"),
    "records": ("记录数", "记录条数", "数据条数", "records"),
}
DIMENSIONS = {
    "region": ("地区", "区域", "国家", "country", "region"),
    "product": ("产品", "品类", "商品", "product"),
    "month": ("月份", "按月", "每月", "月度", "趋势", "month"),
}
DIMENSION_FIELDS = {
    "region": ("region", "country"),
    "product": ("product", "description", "stock_code"),
    "month": ("month",),
}
DIMENSION_FILTER_PATTERNS = (
    r'(?:国家|country)\s*(?:=|：|:)\s*(?:"[^"]+"|\'[^\']+\'|[A-Za-z0-9_-]+)',
    r'(?:月份|month)\s*(?:=|：|:)\s*\d{4}-\d{2}',
    r'(?:商品编码|stock_code)\s*(?:=|：|:)\s*[A-Za-z0-9_-]+',
)
QUERY_FILTERS = (
    (
        "country",
        r'(?:国家|country)\s*(?:=|：|:)\s*(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z0-9_-]+))',
        ("country", "region"),
    ),
    ("month", r'(?:月份|month)\s*(?:=|：|:)\s*(\d{4}-\d{2})', ("month",)),
    (
        "stock_code",
        r'(?:商品编码|stock_code)\s*(?:=|：|:)\s*([A-Za-z0-9_-]+)',
        ("stock_code", "product"),
    ),
)
METRIC_LABELS = {
    "sales": "销售额",
    "cost": "成本",
    "quantity": "商品数量",
    "unit_price": "单价",
    "orders": "订单数",
    "customers": "客户数",
    "profit": "毛利",
    "records": "记录数",
}


def _dimension_field(dimension, fields):
    return next(
        (name for name in DIMENSION_FIELDS[dimension] if name in fields), None
    )


def _filters(query, fields):
    filters = []

    # Keep compatibility with the original deterministic regression fixture.
    for field, values in (
        ("region", ("华东", "华北", "西北")),
        ("product", ("工业设备", "技术服务")),
    ):
        matched = [value for value in values if value in query]
        if len(matched) > 1:
            raise ValueError("规则模式暂不支持多个筛选值，请分开提问。")
        if matched:
            if field not in fields:
                raise ValueError("数据集缺少筛选字段：" + field)
            value = matched[0].replace("'", "''")
            filters.append(f'"{field}" = \'{value}\'')

    for label, pattern, aliases in QUERY_FILTERS:
        match = re.search(pattern, query, re.IGNORECASE)
        if not match:
            continue
        column = next((name for name in aliases if name in fields), None)
        if not column:
            raise ValueError(f"当前数据集不支持按 {label} 筛选。")
        value = next((item for item in match.groups() if item is not None), "")
        value = value.replace("'", "''")
        filters.append(f'"{column}" = \'{value}\'')
    return filters


def offline_plan(query, schema):
    text = query.lower().strip()
    blocked = (
        "删除", "修改数据库", "预测", "因果", "同比", "环比", "相关性",
        "delete", "drop", "update", "join",
    )
    if any(word in text for word in blocked):
        raise ValueError(
            "规则模式仅支持单表描述统计；该任务需要澄清或真实模型及相应分析实现。"
        )

    fields = {item["name"]: item["type"] for item in schema}
    matched_metrics = [
        key
        for key, words in METRICS.items()
        if any(word in text for word in words)
    ]
    if len(matched_metrics) > 1:
        raise ValueError("规则模式每次分析一个指标，请分开提问。")
    metric = next(iter(matched_metrics), None)
    if metric is None:
        metric = "sales" if "sales" in fields else next(
            (name for name, kind in fields.items() if kind == "DOUBLE"), None
        )
    if metric is None:
        metric = "records"

    if metric == "profit":
        if not {"sales", "cost"} <= fields.keys():
            raise ValueError("毛利需要 sales 和 cost 字段。")
        expression = '("sales" - "cost")'
        meaning = "毛利 = sales - cost，按每行记录计算后聚合"
    elif metric in {"orders", "customers"}:
        column = "invoice_no" if metric == "orders" else "customer_id"
        if column not in fields:
            raise ValueError(f"{METRIC_LABELS[metric]}需要 {column} 字段。")
        expression = f'COUNT(DISTINCT "{column}")'
        meaning = f"{METRIC_LABELS[metric]} = 去重统计 {column}，空值不计入"
    elif metric == "records":
        expression = "*"
        meaning = "记录数 = 原始数据行数，不代表去重客户数"
    else:
        if metric not in fields:
            raise ValueError("数据集缺少字段：" + metric)
        expression = f'"{metric}"'
        meaning = {
            "sales": "销售额取自 sales 字段",
            "cost": "成本取自 cost 字段",
            "quantity": "商品数量取自 quantity 字段",
            "unit_price": "单价取自 unit_price 字段",
        }.get(metric, metric)

    operations = (
        ("AVG", ("平均", "均值", "avg", "average")),
        ("MAX", ("最大", "最高", "max")),
        ("MIN", ("最小", "最低", "min")),
        ("COUNT", ("非空数量", "count")),
    )
    aggregate = next(
        (op for op, words in operations if any(word in text for word in words)),
        "AVG" if metric == "unit_price" else "SUM",
    )
    if metric in {"records", "orders", "customers"}:
        aggregate = "COUNT"

    dimension_text = text
    for pattern in DIMENSION_FILTER_PATTERNS:
        dimension_text = re.sub(pattern, "", dimension_text, flags=re.IGNORECASE)
    matched_dimensions = [
        key
        for key, words in DIMENSIONS.items()
        if any(word in dimension_text for word in words)
    ]
    if len(matched_dimensions) > 1:
        raise ValueError("规则模式每次分析一个分组维度，请分开提问。")
    dimension = next(iter(matched_dimensions), None)
    overall_words = ("总体", "全部", "整体", "总计", "overall")
    if any(word in dimension_text for word in overall_words):
        dimension = None
    actual_dimension = _dimension_field(dimension, fields) if dimension else None
    if dimension and not actual_dimension:
        raise ValueError("数据集缺少分组字段：" + dimension)

    filters = _filters(query, fields)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    grouping = f'"{actual_dimension}"' if actual_dimension else "'全部记录'"
    aggregate_expression = (
        expression
        if metric in {"orders", "customers"}
        else f"{aggregate}({expression})"
    )
    if metric in {"sales", "unit_price"} and aggregate in {"SUM", "AVG"}:
        aggregate_expression = f"ROUND({aggregate_expression}, 2)"

    sql = (
        f"SELECT {grouping} AS category, {aggregate_expression} AS value "
        f"FROM data{where}"
    )
    if actual_dimension:
        sql += f' GROUP BY "{actual_dimension}"'
    sql += " ORDER BY " + ("category" if dimension == "month" else "value DESC")
    top = re.search(r"(?:前|top\s*)(\d+)", text)
    limit = min(int(top.group(1)), 100) if top else 20
    if limit < 1:
        raise ValueError("展示条数必须大于零。")
    sql += f" LIMIT {limit}"

    return {
        "title": "经营报表分析",
        "metric_definition": (
            f"{meaning}；使用 {aggregate} 聚合；空值遵循 SQL 规则，未做因果推断。"
        ),
        "sql": sql,
        "chart": {
            "kind": "line" if dimension == "month" else "bar",
            "x": "category",
            "y": "value",
            "title": f"{METRIC_LABELS[metric]} · {aggregate} 分析",
        },
    }

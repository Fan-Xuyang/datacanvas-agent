"""Explicit, bounded offline planner; not a substitute for a measured LLM."""
import re

METRICS = {
    'sales': ('销售额', '销售收入', '营收', 'sales'),
    'cost': ('成本', '支出', 'cost'),
    'orders': ('订单量', '订单数', 'orders'),
    'profit': ('毛利', '利润', 'profit'),
    'records': ('记录数', '记录条数', '数据条数', 'records'),
}
DIMENSIONS = {'region': ('地区', '区域', 'region'), 'product': ('产品', '品类', 'product'), 'month': ('月份', '按月', '每月', '月度', '趋势', 'month')}


def offline_plan(query, schema):
    text = query.lower().strip()
    if any(word in text for word in ['删除', '修改数据库', '预测', '因果', '同比', '环比', '相关性', 'delete', 'drop', 'update', 'join']):
        raise ValueError('规则模式仅支持单表描述统计；该任务需要澄清或真实模型及相应分析实现。')
    fields = {x['name']:x['type'] for x in schema}
    matched_metrics = [key for key,words in METRICS.items() if any(w in text for w in words)]
    if len(matched_metrics)>1:
        raise ValueError('规则模式每次分析一个指标，请分开提问。')
    metric = next(iter(matched_metrics), None)
    if not metric:
        # Existing generic example still resolves to the explicit sales field.
        metric = 'sales' if 'sales' in fields else next((n for n,t in fields.items() if t=='DOUBLE'), None)
    if not metric:
        metric='records'
    if metric=='profit':
        if not {'sales','cost'}<=fields.keys():raise ValueError('毛利需要 sales 和 cost 字段。')
        expression='("sales" - "cost")'
        meaning='毛利 = sales - cost，按每行记录计算后聚合'
    elif metric=='records':
        expression='*'
        meaning='记录数 = 原始数据行数，不代表去重客户数'
    else:
        if metric not in fields:raise ValueError('数据集缺少字段：'+metric)
        expression='"'+metric+'"'
        meaning=metric
    aggregate=next((op for op,words in [('AVG',('平均','均值','avg','average')),('MAX',('最大','最高','max')),('MIN',('最小','最低','min')),('COUNT',('非空数量','count'))] if any(w in text for w in words)), 'SUM')
    if metric=='records':aggregate='COUNT'
    matched_dimensions=[key for key,words in DIMENSIONS.items() if any(w in text for w in words)]
    if len(matched_dimensions)>1:
        raise ValueError('规则模式每次分析一个分组维度，请分开提问。')
    dimension=next(iter(matched_dimensions),None)
    if any(word in text for word in ['总体','全部','整体','总计','overall']):dimension=None
    if dimension and dimension not in fields:raise ValueError('数据集缺少分组字段：'+dimension)
    # Do not quietly drop arbitrary user filters. Support a finite, documented equality filter.
    filters=[]
    for field,values in [('region',['华东','华北','西北']),('product',['工业设备','技术服务'])]:
        matched=[v for v in values if v in query]
        if len(matched)>1:raise ValueError('规则模式暂不支持多个筛选值，请分开提问。')
        if matched:
            if field not in fields:raise ValueError('数据集缺少筛选字段：'+field)
            filters.append('"'+field+'" = \''+matched[0]+"'")
    where=' WHERE '+' AND '.join(filters) if filters else ''
    grouping='"'+dimension+'"' if dimension else "'全部记录'"
    sql=f'SELECT {grouping} AS category, {aggregate}({expression}) AS value FROM data'+where
    if dimension:sql+=' GROUP BY "'+dimension+'"'
    sql+=' ORDER BY '+('category' if dimension=='month' else 'value DESC')
    top=re.search(r'(?:前|top\s*)(\d+)',text)
    limit=min(int(top.group(1)),100) if top else 20
    if limit<1:raise ValueError('展示条数必须大于零。')
    sql+=f' LIMIT {limit}'
    return {'title':'经营报表分析','metric_definition':f'{meaning}；使用 {aggregate} 聚合；空值遵循 SQL 规则，未做因果推断。','sql':sql,'chart':{'kind':'line' if dimension=='month' else 'bar','x':'category','y':'value','title':f'{metric} {aggregate} 分析'}}

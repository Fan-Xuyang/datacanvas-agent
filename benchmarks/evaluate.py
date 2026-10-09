import argparse
import asyncio
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.agent import demo_plan
from app.baseline_v1 import demo_plan as baseline_plan
from app.data import ingest, execute
from shared.store import Store


def oracle(rows,spec):
    buckets=defaultdict(list)
    for row in rows:
        if any(row[k]!=v for k,v in spec.get('filter',{}).items()):continue
        key=row[spec['dimension']] if spec['dimension'] else '全部记录'
        metric=spec['metric']
        value=1 if metric=='records' else float(row['sales'])-float(row['cost']) if metric=='profit' else float(row[metric])
        buckets[key].append(value)
    op=spec['aggregate']
    funcs={'SUM':sum,'AVG':statistics.mean,'MAX':max,'MIN':min,'COUNT':len}
    return {key:float(funcs[op](values)) for key,values in buckets.items()}


def matches(result,expected):
    actual={str(r[0]):r[1] for r in result['rows']}
    return actual.keys()==expected.keys() and all(abs(float(actual[k])-v)<1e-6 for k,v in expected.items())


async def main():
    suite_path=ROOT/'benchmarks/cases.json'
    suite=json.loads(suite_path.read_text(encoding='utf-8'))
    rows=list(csv.DictReader((ROOT/'examples/sales.csv').open(encoding='utf-8')))
    outputs={}
    with tempfile.TemporaryDirectory() as temp:
        store=Store(Path(temp)/'state.db')
        ds=ingest(temp,store,'sales.csv',(ROOT/'examples/sales.csv').read_bytes())
        for name,planner in [('v1',baseline_plan),('v2',demo_plan)]:
            results=[]
            for case in suite['cases']:
                start=time.perf_counter();error=None;correct=False
                try:
                    plan=planner(case['query'],ds['schema'])
                    result=await execute(Path(temp)/f"{ds['id']}.duckdb",plan.sql)
                    correct=matches(result,oracle(rows,case['expected']))
                except Exception as exc:error=str(exc)
                results.append({'id':case['id'],'query':case['query'],'correct':correct,'error':error,'latency_ms':round((time.perf_counter()-start)*1000,2)})
            refused=0
            for text in suite['negative']:
                try:planner(text,ds['schema'])
                except ValueError:refused+=1
            latencies=sorted(x['latency_ms'] for x in results)
            outputs[name]={'correct':sum(x['correct'] for x in results),'total':len(results),'result_consistency_percent':round(100*sum(x['correct'] for x in results)/len(results),2),'negative_rejected':refused,'negative_total':len(suite['negative']),'p50_ms':round(statistics.median(latencies),2),'p95_ms':latencies[int(.95*(len(latencies)-1))],'cases':results}
            print(name,outputs[name]['correct'],'/',len(results),flush=True)
    report={'scope':'合成规则规划器功能回归，查询经真实 DuckDB 子进程执行；不代表模型准确率。','dataset_rows':len(rows),'suite_sha256':hashlib.sha256(suite_path.read_bytes()).hexdigest(),'python':platform.python_version(),'platform':platform.platform(),'model':'none','results':outputs}
    (ROOT/'benchmarks/results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    current=outputs['v2']
    if current['correct']!=current['total'] or current['negative_rejected']!=current['negative_total']:
        raise SystemExit('Rule regression failed; inspect benchmarks/results.json.')

if __name__=='__main__':asyncio.run(main())

import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactMarkdown from 'react-markdown';
echarts.use([BarChart,LineChart,GridComponent,TooltipComponent,CanvasRenderer]);

type Dataset={id:string;name:string;rows:number;schema:{name:string;type:string}[]};
type Trace={seq:number;type:string;payload:Record<string,unknown>;created:number};
type Task={id:string;query:string;mode:string;status:string;events:Trace[];state:{dataset?:Dataset;plan?:{title?:string;goal?:string;metric_definition?:string;sql?:string;chart?:{kind:string;x:string;y:string;title:string};payload?:Record<string,string|number>};result?:{columns:string[];rows:(string|number|null)[][];truncated:boolean;checksum:string};digest?:string;screenshot?:string;receipt?:{receipt:string};report?:string;usage?:{input_tokens:number|null;output_tokens:number|null;latency_ms:number}[]}};
type TaskSummary=Pick<Task,'id'|'query'|'status'|'mode'>;
type KnowledgeDoc={id:string;filename:string;sha256:string;bytes:number;chunks:number;created:number};
type KnowledgeHit={id:string;document_id:string;filename:string;page:number;content:string;score:number};
type QualityProfile={rows:number;fields:{name:string;type:string;null_count:number;distinct_count:number}[];issues:{field:string|null;type:string;count:number}[]};
type OpsMetrics={tasks_by_status:Record<string,number>;datasets:number;knowledge_documents:number;model_calls:number;input_tokens:number;output_tokens:number;model_latency_ms:number};
type DatasetLineage={source_name:string;source_sha256:string;ingested_at:number;row_count:number;column_count:number};
const labels:Record<string,string>={queued:'排队中',running:'执行中',completed:'已完成',failed:'执行失败',awaiting_approval:'等待确认',interrupted:'已中断',cancelled:'已取消'};
const prompts=['按国家汇总销售额','按月份查看销售额趋势','按商品汇总销售额','按国家统计订单数','按国家统计不同客户数','按国家查看平均单价'];

function formatValue(value:string|number|null){
  if(value===null)return '—';
  if(typeof value==='number')return new Intl.NumberFormat('en-GB',{maximumFractionDigits:2}).format(value);
  return value;
}

function downloadCsv(task:Task){
  const result=task.state.result;if(!result)return;
  const cell=(value:unknown)=>{
    let text=String(value??'');
    if(typeof value==='string'&&/^\s*[=+\-@]/.test(text))text="'"+text;
    return '"'+text.replaceAll('"','""')+'"';
  };
  const csv='\ufeff'+[result.columns,...result.rows].map(row=>row.map(cell).join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const anchor=document.createElement('a');anchor.href=url;anchor.download='datacanvas-result.csv';anchor.click();
  window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}

async function api(path:string,body?:unknown){
  const response=await authedFetch('/api/'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  if(!response.ok){let text='请求失败';try{const data=await response.json();text=data.detail||text;}catch{try{text=(await response.text())||text;}catch{}}throw Error(text);}
  return response.json();
}

function authedFetch(url:string,init:RequestInit={}){
  const headers=new Headers(init.headers),token=sessionStorage.getItem('datacanvas-token');if(token)headers.set('Authorization','Bearer '+token);
  return fetch(url,{...init,headers});
}

async function watchEvents(url:string,signal:AbortSignal,onTrace:(event:Trace)=>void){
  const headers=new Headers(),token=sessionStorage.getItem('datacanvas-token');if(token)headers.set('Authorization','Bearer '+token);
  const response=await fetch(url,{headers,signal});if(!response.ok||!response.body)throw Error('事件流连接失败');
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  while(true){const {value,done}=await reader.read();if(done)return;buffer+=decoder.decode(value,{stream:true});let boundary;
    while((boundary=buffer.indexOf('\n\n'))>=0){const frame=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);let event='message',data='';
      for(const line of frame.split(/\r?\n/)){if(line.startsWith('event:'))event=line.slice(6).trim();if(line.startsWith('data:'))data+=line.slice(5).trim();}
      if(event==='trace'&&data)onTrace(JSON.parse(data) as Trace);if(event==='settled')return;
    }
  }
}

function Chart({task}:{task:Task}){
  const element=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const spec=task.state.plan?.chart,data=task.state.result;
    if(!element.current||!spec||!data||spec.kind==='table')return;
    const chart=echarts.init(element.current);
    const xi=data.columns.indexOf(spec.x),yi=data.columns.indexOf(spec.y);
    chart.setOption({color:['#6c60dd'],tooltip:{trigger:'axis',renderMode:'richText'},grid:{left:65,right:22,top:28,bottom:65},xAxis:{type:'category',data:data.rows.map(r=>r[xi]),axisLabel:{rotate:data.rows.length>8?25:0,color:'#68718a'}},yAxis:{type:'value',axisLabel:{color:'#68718a'},splitLine:{lineStyle:{color:'#edf0f7'}}},series:[{type:spec.kind,data:data.rows.map(r=>r[yi]),barMaxWidth:55,smooth:false,itemStyle:{borderRadius:[5,5,0,0]}}]});
    const observer=new ResizeObserver(()=>chart.resize());observer.observe(element.current);
    return()=>{observer.disconnect();chart.dispose();};
  },[task]);
  return <div className="chart" ref={element} aria-label="查询结果图表"/>;
}

export default function App(){
  const [kind,setKind]=useState('data'),[configured,setConfigured]=useState(false),[authRequired,setAuthRequired]=useState(false),[tokenInput,setTokenInput]=useState(''),[datasets,setDatasets]=useState<Dataset[]>([]),[dataset,setDataset]=useState(''),[quality,setQuality]=useState<QualityProfile|null>(null),[lineage,setLineage]=useState<DatasetLineage|null>(null),[opsMetrics,setOpsMetrics]=useState<OpsMetrics|null>(null);
  const [tasks,setTasks]=useState<TaskSummary[]>([]),[task,setTask]=useState<Task|null>(null),[query,setQuery]=useState(''),[mode,setMode]=useState('demo');
  const [knowledgeDocs,setKnowledgeDocs]=useState<KnowledgeDoc[]>([]),[knowledgeQuery,setKnowledgeQuery]=useState(''),[knowledgeAnswer,setKnowledgeAnswer]=useState(''),[knowledgeHits,setKnowledgeHits]=useState<KnowledgeHit[]>([]),[knowledgeBusy,setKnowledgeBusy]=useState(false),[knowledgeUploading,setKnowledgeUploading]=useState(false);
  const [metric,setMetric]=useState('销售额 = SUM(sales)，不含币种换算；按数据文件原始口径。'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[uploading,setUploading]=useState(false),[copied,setCopied]=useState(false);
  const stream=useRef<AbortController|null>(null),selected=useRef<string|null>(null);
  const browser=kind==='browser';
  async function refresh(){const [taskRows,stats]=await Promise.all([api('tasks'),api('metrics')]);setTasks(taskRows);setOpsMetrics(stats);}
  async function refreshData(){const data=await api('datasets');setDatasets(data);setDataset(id=>id||data.find((d:Dataset)=>d.name==='uci_online_retail_sample.csv')?.id||data[0]?.id||'');}
  async function refreshKnowledge(){setKnowledgeDocs(await api('knowledge'));}
  async function load(id:string,connect=true){
    selected.current=id;const data:Task=await api('tasks/'+id);if(selected.current!==id)return;setTask(data);
    stream.current?.abort();
    if(connect&&['running','queued'].includes(data.status)){
      const after=data.events.at(-1)?.seq||0;
      const controller=new AbortController();stream.current=controller;
      void watchEvents('/api/tasks/'+id+'/events?after='+after,controller.signal,event=>{setTask(t=>t?.id===id?{...t,events:t.events.some(x=>x.seq===event.seq)?t.events:[...t.events,event]}:t);})
        .then(()=>{if(controller.signal.aborted)return;if(selected.current===id)void load(id,false).catch(e=>setError(e.message));void refresh();})
        .catch(e=>{if(!controller.signal.aborted)setError((e as Error).message);});
    }
  }
  useEffect(()=>{api('health').then(h=>{setKind(h.kind);setConfigured(h.live_configured);setAuthRequired(h.auth_required);if(h.kind==='data'){void refreshData().catch(e=>setError(e.message));void refreshKnowledge().catch(e=>setError(e.message));}}).catch(e=>setError(e.message));void refresh().catch(e=>setError(e.message));return()=>stream.current?.abort();},[]);
  async function run(){setBusy(true);setError('');try{const created=await api('tasks',{query,mode,dataset_id:dataset,metrics:browser?{}:{销售额:metric}});await load(created.id);await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function action(name:string,body:unknown={}){if(!task)return;setBusy(true);setError('');try{await api('tasks/'+task.id+'/'+name,body);await load(task.id);await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function upload(file:File){setUploading(true);setError('');try{const form=new FormData();form.append('file',file);const response=await authedFetch('/api/datasets',{method:'POST',body:form});const data=await response.json();if(!response.ok)throw Error(data.detail||'数据导入失败');await refreshData();setDataset(data.id);}catch(e){setError((e as Error).message);}finally{setUploading(false);}}
  async function uploadKnowledge(file:File){setKnowledgeUploading(true);try{const form=new FormData();form.append('file',file);const response=await authedFetch('/api/knowledge',{method:'POST',body:form});const data=await response.json();if(!response.ok)throw Error(data.detail||'文档导入失败');await refreshKnowledge();setKnowledgeQuery(file.name.replace(/\.[^.]+$/,''));}catch(e){setError((e as Error).message);}finally{setKnowledgeUploading(false);}}
  async function askKnowledge(){if(!knowledgeQuery.trim())return;setKnowledgeBusy(true);setKnowledgeAnswer('');setKnowledgeHits([]);try{const response=await authedFetch('/api/knowledge/answer?q='+encodeURIComponent(knowledgeQuery));const data=await response.json();if(!response.ok)throw Error(data.detail||'知识检索失败');setKnowledgeAnswer(data.answer);setKnowledgeHits(data.citations||[]);}catch(e){setError((e as Error).message);}finally{setKnowledgeBusy(false);}}
  async function removeKnowledge(id:string){try{const response=await authedFetch('/api/knowledge/'+id,{method:'DELETE'});if(!response.ok)throw Error('删除文档失败');await refreshKnowledge();if(knowledgeHits.some(hit=>hit.document_id===id)){setKnowledgeHits([]);setKnowledgeAnswer('');}}catch(e){setError((e as Error).message);}}
  async function downloadReport(id:string){try{const response=await authedFetch('/api/tasks/'+id+'/report');if(!response.ok)throw Error('报告下载失败');const url=URL.createObjectURL(await response.blob()),anchor=document.createElement('a');anchor.href=url;anchor.download='datacanvas-'+id.slice(0,8)+'.md';anchor.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){setError((e as Error).message);}}
  async function saveToken(){sessionStorage.setItem('datacanvas-token',tokenInput.trim());setTokenInput('');setError('');try{await refresh();if(kind==='data'){await refreshData();await refreshKnowledge();}}catch(e){setError((e as Error).message);}}
  useEffect(()=>{if(dataset){void Promise.all([api('datasets/'+dataset+'/profile'),api('datasets/'+dataset+'/lineage').catch(()=>null)]).then(([profile,source])=>{setQuality(profile);setLineage(source);}).catch(()=>{setQuality(null);setLineage(null);});}else{setQuality(null);setLineage(null);}},[dataset]);
  const result=task?.state.result,plan=task?.state.plan;
  const currentDataset=datasets.find(d=>d.id===dataset);
  const isOpenDataset=currentDataset?.name==='uci_online_retail_sample.csv';
  const usage=task?.state.usage?.reduce((a,b)=>({input:a.input+(b.input_tokens||0),output:a.output+(b.output_tokens||0),ms:a.ms+b.latency_ms}),{input:0,output:0,ms:0});
  return <div className={'app '+(browser?'flow':'data')}>
    <aside><a className="brand" href="/"><span>{browser?'F':'TL'}</span><div>{browser?'FlowPilot':'天力复材'}<small>{browser?'采购流程工作台':'材料数据智能平台'}</small></div></a>
      <button className="new-task" onClick={()=>{selected.current=null;stream.current?.abort();setTask(null);setQuery('');setError('');}}>＋ 新建任务</button>
      <div className="side-heading">任务记录 <span>{tasks.length}</span></div><nav>{tasks.map(t=><button key={t.id} className={task?.id===t.id?'selected':''} onClick={()=>void load(t.id).catch(e=>setError(e.message))}><span>{t.query}</span><small>{labels[t.status]} · {t.mode==='demo'?'规则':'大模型'}</small></button>)}</nav>
      {!browser&&<><div className="side-heading">数据集 <span>{datasets.length}</span></div><label className="upload">{uploading?'导入中…':'↑ 导入 CSV / Excel'}<input type="file" accept=".csv,.xlsx" disabled={uploading} onChange={e=>{const f=e.target.files?.[0];if(f)void upload(f);e.target.value='';}}/></label><p className="tiny">最大 5 MB / 20,000 行。已内置 UCI 真实零售交易开放数据。</p><div className="dataset-list">{datasets.map(d=><button key={d.id} className={d.id===dataset?'selected':''} onClick={()=>setDataset(d.id)}>{d.name}<small>{d.rows} 行 · {d.schema.length} 列</small></button>)}</div></>}
      {authRequired&&<details className="auth-panel"><summary>共享工作区登录</summary><input type="password" value={tokenInput} onChange={e=>setTokenInput(e.target.value)} placeholder="粘贴访问令牌" autoComplete="current-password"/><button onClick={()=>void saveToken()} disabled={!tokenInput.trim()}>连接工作区</button></details>}
      <footer>西安天力金属复合材料股份有限公司<br/>材料经营分析 · 知识检索 · 数据治理</footer></aside>
    <main><header className={browser?'page-header':'company-hero'}>{!browser&&<img className="company-hero-image" src="/assets/tianli-clad-materials-hero.png" alt="金属复合板材与现代制造产线场景示意图"/>}<div className="company-hero-copy"><p className="eyebrow">{browser?'采购流程工作台':'西安天力金属复合材料股份有限公司 · 材料数据智能平台'}</p><h1>{browser?'采购申请协同工作台':'让复合材料经营数据更清晰'}</h1><p className="subtitle">{browser?'集中填写申请信息，完成校验、确认和流程回执。':'围绕钛钢、锆钢、不锈钢等层状金属复合材料业务，提供自然语言分析、知识检索与可复核报告。'}</p>{!browser&&<div className="material-chips"><span>钛-钢复合材料</span><span>锆-钢复合材料</span><span>不锈钢-钢复合材料</span><span>钽-钢复合材料</span></div>}</div><span className="local">● 服务正常</span></header>
      {!browser&&quality&&<section className="quality-summary"><div><span className="section-kicker">数据质量与血缘</span><strong>{quality.rows.toLocaleString()} 行 · {quality.fields.length} 个字段</strong>{lineage&&<small>来源 {lineage.source_name} · SHA-256 {lineage.source_sha256.slice(0,12)}… · {new Date(lineage.ingested_at*1000).toLocaleString()}</small>}</div><div><b>{quality.issues.length}</b><small>项质量提示</small></div><div><b>{quality.issues.find(x=>x.type==='duplicate_rows')?.count||0}</b><small>重复记录</small></div><details><summary>查看字段检查</summary><ul>{quality.fields.map(field=><li key={field.name}>{field.name}：空值 {field.null_count} · 唯一值 {field.distinct_count}</li>)}</ul><ul>{quality.issues.map((issue,i)=><li key={i}>{issue.field||'整行'} · {issue.type} · {issue.count}</li>)}</ul></details></section>}
      {opsMetrics&&<section className="ops-summary"><div><b>{Object.values(opsMetrics.tasks_by_status).reduce((a,b)=>a+b,0)}</b><small>分析任务</small></div><div><b>{opsMetrics.model_calls}</b><small>模型调用</small></div><div><b>{(opsMetrics.input_tokens+opsMetrics.output_tokens).toLocaleString()}</b><small>Token 用量</small></div><div><b>{Math.round(opsMetrics.model_latency_ms/Math.max(opsMetrics.model_calls,1))} ms</b><small>平均模型耗时</small></div><div><b>{opsMetrics.knowledge_documents}</b><small>知识文档</small></div></section>}
      {!browser&&<section className="dataset-overview"><div className="dataset-overview-top"><div><span className="section-kicker">当前数据集</span><h2>{currentDataset?.name||'正在读取数据集…'}</h2><p>{isOpenDataset?'UCI Online Retail · 英国线上零售交易 · 2010.12—2011.12':'当前表格已载入本地分析空间'}</p></div><span className={'source-pill '+(isOpenDataset?'open-source':'')}>{isOpenDataset?'开放数据 · CC BY 4.0':'本地数据'}</span></div><div className="overview-stats"><div><span>数据记录</span><strong>{currentDataset?.rows.toLocaleString('zh-CN')||'—'}</strong></div><div><span>可用字段</span><strong>{currentDataset?.schema.length||'—'}</strong></div><div><span>当前引擎</span><strong>DuckDB</strong></div><div><span>查询方式</span><strong>只读 SQL</strong></div></div></section>}
      <section className="composer"><div className="composer-top"><label>分析模式 <select value={mode} onChange={e=>setMode(e.target.value)}><option value="demo">规则规划</option><option value="live" disabled={!configured}>大模型规划{configured?'':'（暂不可用）'}</option></select></label><span>{mode==='demo'?'规则规划 · 实际执行 SQL 与数据分析流程':'调用已配置的大模型服务'}</span></div>
      <div className="query-heading"><label className="question-label" htmlFor="query">{browser?'填写本次采购需求':'想了解什么？'}</label><span>自然语言提问 · 自动生成 SQL</span></div><textarea id="query" placeholder={browser?'例如：为研发部申请 3 台笔记本电脑，预算 18000 元，用于开发测试。':'例如：按国家汇总销售额，或统计不同客户数。'} value={query} maxLength={2000} onChange={e=>setQuery(e.target.value)}/>
      <p className="tiny">{browser?'支持信息技术部、研发部、综合管理部；按采购申请规则校验缺失字段。':'支持销售额、商品数量、平均单价、订单数、客户数；按国家、商品或月份分组。筛选示例：国家=France、月份=2011-11、商品编码=85123A。'}</p>
      {!browser&&<div className="prompt-list" aria-label="常用分析"><span>试试：</span>{prompts.map(item=><button key={item} className="prompt-chip" onClick={()=>setQuery(item)}>{item}</button>)}</div>}
      {!browser&&<details className="metrics"><summary>指标口径与字段</summary><input aria-label="指标口径" value={metric} onChange={e=>setMetric(e.target.value)} maxLength={300}/><p>{currentDataset?.schema.map(x=>x.name+' ('+x.type+')').join(' · ')}</p></details>}
      <div className="composer-actions"><span className="privacy-note">数据按授权范围处理 · 结果可下载复核</span><button className="primary" disabled={busy||!query.trim()||(!browser&&!dataset)} onClick={run}>{busy?'正在分析…':browser?'准备执行 ↗':'生成分析 ↗'}</button></div></section>
      {!browser&&<section className="knowledge-panel"><div className="knowledge-head"><div><span className="section-kicker">RAG · 检索增强生成</span><h2>企业知识库</h2><p>导入制度、产品资料或技术文档，检索片段附原文来源。</p></div><label className="knowledge-upload">{knowledgeUploading?'正在解析…':'＋ 导入文档'}<input type="file" accept=".pdf,.txt,.md,.csv" disabled={knowledgeUploading} onChange={e=>{const f=e.target.files?.[0];if(f)void uploadKnowledge(f);e.target.value='';}}/></label></div><div className="knowledge-search"><input aria-label="知识库问题" value={knowledgeQuery} onChange={e=>setKnowledgeQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')void askKnowledge();}} placeholder="问一个需要查阅资料的问题…"/><button className="secondary-button" disabled={knowledgeBusy||!knowledgeQuery.trim()} onClick={()=>void askKnowledge()}>{knowledgeBusy?'检索中…':'检索并回答'}</button></div><div className="knowledge-meta"><span>{knowledgeDocs.length} 份文档</span><span>PDF · TXT · Markdown · CSV</span><span>{configured?'生成模型已连接':'未配置模型时提供检索原文'}</span></div>{knowledgeAnswer&&<div className="knowledge-response"><strong>回答</strong><p>{knowledgeAnswer}</p>{knowledgeHits.length>0&&<div className="knowledge-citations">{knowledgeHits.map(hit=><article key={hit.id}><div><b>{hit.filename}</b><span>第 {hit.page} 页 · 相关度 {hit.score}</span></div><p>{hit.content}</p></article>)}</div>}</div>}{knowledgeDocs.length>0&&<div className="knowledge-files">{knowledgeDocs.map(doc=><div key={doc.id}><span className="file-dot">●</span><div><strong>{doc.filename}</strong><small>{doc.chunks} 个检索片段 · {(doc.bytes/1024).toFixed(0)} KB</small></div><button aria-label={'删除 '+doc.filename} onClick={()=>void removeKnowledge(doc.id)}>删除</button></div>)}</div>}</section>}
      {error&&<div className="error" role="alert">{error}</div>}
      {task&&<div className="task-status"><span className={'pill '+task.status}>{labels[task.status]}</span><code>任务 {task.id.slice(0,8)}</code><span className="grow"/>{task.status==='interrupted'&&<button onClick={()=>void action('resume')} disabled={busy}>恢复任务</button>}{['running','queued','awaiting_approval','interrupted'].includes(task.status)&&<button onClick={()=>void action('cancel')} disabled={busy}>取消任务</button>}{task.state.report&&<button onClick={()=>void downloadReport(task.id)}>导出 Markdown ↓</button>}</div>}
      <div className="work-area"><section className="results"><div className="panel-heading"><h2>{browser?'执行结果与确认':'图表与分析证据'}</h2><span className="tiny">{task?.mode==='demo'?'规则规划 · SQL 已校验执行':''}</span></div>
      {!task?<div className="empty"><span>{browser?'⌘':'▥'}</span><h3>{browser?'先描述任务，再检查执行过程':'从一份数据和一个问题开始'}</h3><p>{browser?'内置采购门户支持完整的填写、确认和回执验证。':'内置 UCI 真实零售交易样本，也可上传自己的 CSV / Excel。'}</p></div>:<>
      {plan&&<div className="plan"><div className="plan-heading"><div><span className="section-kicker">分析口径</span><h3>{plan.chart?.title||plan.title||plan.goal}</h3></div>{plan.sql&&<button className="subtle-button" onClick={()=>{void navigator.clipboard.writeText(plan.sql||'').then(()=>{setCopied(true);window.setTimeout(()=>setCopied(false),1500);});}}>{copied?'已复制':'复制 SQL'}</button>}</div><p>{plan.metric_definition}</p>{plan.sql&&<pre><code>{plan.sql}</code></pre>}</div>}
      {result&&<><div className="result-heading"><div><span className="section-kicker">分析结果</span><h3 className="chart-title">{plan?.chart?.title}</h3></div><button className="subtle-button" onClick={()=>downloadCsv(task)}>下载 CSV</button></div>{plan?.chart?.kind!=='table'&&<Chart task={task}/>}<div className="table-scroll"><table><thead><tr>{result.columns.map((c,i)=><th key={i}>{c==='category'?'分组':c==='value'?'指标值':c}</th>)}</tr></thead><tbody>{result.rows.slice(0,100).map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{formatValue(v)}</td>)}</tr>)}</tbody></table></div><p className="tiny">查询返回 {result.rows.length} 行{result.truncated?'（已截断）':''}；页面最多展示 100 行。结果 SHA-256：{result.checksum.slice(0,16)}…</p></>}
      {browser&&plan?.payload&&<dl className="payload">{Object.entries(plan.payload).map(([k,v])=><div key={k}><dt>{{department:'部门',item:'物品',quantity:'数量',budget:'预算上限',reason:'用途'}[k]||k}</dt><dd>{v}</dd></div>)}</dl>}
      {task.status==='awaiting_approval'&&<div className="approval"><h3>请核对本次申请内容</h3><p>确认后将生成采购申请记录，并返回可核验的流程回执。</p><div><button className="primary" disabled={busy} onClick={()=>void action('approve',{digest:task.state.digest,approve:true})}>确认并生成申请回执</button><button disabled={busy} onClick={()=>void action('approve',{digest:task.state.digest,approve:false})}>退回修改</button></div></div>}
      {task.state.receipt&&<div className="receipt"><strong>回执已校验</strong><code>{task.state.receipt.receipt}</code></div>}
      {browser&&task.state.screenshot&&<details className="screenshot" open><summary>浏览器页面截图</summary><img src={'/api/tasks/'+task.id+'/screenshot?v='+task.events.length} alt="Agent 执行后的采购门户页面"/></details>}
      {task.state.report&&<details className="report"><summary>完整证据报告</summary><ReactMarkdown>{task.state.report}</ReactMarkdown></details>}
      {task.status==='failed'&&<div className="error">{String(task.events.at(-1)?.payload.message||'执行失败，请查看轨迹。')}</div>}
      </>}</section>
      <section className="trace"><div className="panel-heading"><h2>执行轨迹</h2><span className="tiny">持久化事件</span></div>{task?.events.length?<ol>{task.events.map(e=><li key={e.seq}><div><strong>{String(e.payload.message||e.type)}</strong><time>{new Date(e.created*1000).toLocaleTimeString('zh-CN')}</time></div><details><summary>{e.type} · #{e.seq}</summary><pre>{JSON.stringify(e.payload,null,2)}</pre></details></li>)}</ol>:<p className="muted">任务启动后展示观察、计划、执行、验证与异常事件。刷新页面后可从左侧任务记录恢复查看。</p>}{usage&&<div className="usage"><h3>模型调用记录</h3><p>输入 {usage.input} / 输出 {usage.output} tokens</p><p>调用耗时合计 {(usage.ms/1000).toFixed(2)} 秒</p></div>}</section></div>
      <p className="bottom-note">{browser?'采购流程按申请字段、页面状态和回执进行校验。':'分析查询使用独立 DuckDB 进程和只读连接；图表使用结构化配置生成。'}</p>
    </main></div>;
}

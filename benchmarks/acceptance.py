"""Real-container acceptance checks; run from /app after docker compose cp."""
import argparse
import asyncio
import csv
import json
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, str(Path.cwd()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8201')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', default='/tmp/container-acceptance.json')
    args = parser.parse_args()
    results = []

    def check(name, condition):
        results.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    with httpx.Client(base_url=args.url, timeout=90) as client:
        deadline = time.monotonic() + 60
        while True:
            try:
                if client.get('/api/health').status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError('Application did not become ready in 60 seconds')
            time.sleep(0.5)
        health = client.get('/api/health').json()
        check('health', health['status'] == 'ok')
        check('frontend', client.get('/').status_code == 200)
        datasets = client.get('/api/datasets').json()
        dataset = next(d for d in datasets if d['name'] == 'uci_online_retail_sample.csv')
        check('open_dataset_rows', dataset['rows'] == 20000)
        check('quality_profile', client.get(f"/api/datasets/{dataset['id']}/profile").json()['rows'] == 20000)
        check('source_lineage', client.get(f"/api/datasets/{dataset['id']}/lineage").status_code == 200)

        def run_task(mode):
            response = client.post('/api/tasks', json={
                'query': '按国家汇总销售额，前100组', 'mode': mode,
                'dataset_id': dataset['id'], 'metrics': {'销售额': 'SUM(sales)'},
            })
            response.raise_for_status()
            task_id = response.json()['id']
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                task = client.get('/api/tasks/' + task_id).json()
                if task['status'] not in ('running', 'queued'):
                    break
                time.sleep(0.25)
            check(mode + '_task_completed', task['status'] == 'completed')
            expected = sum(Decimal(row['sales']) for row in csv.DictReader(
                Path('examples/uci_online_retail_sample.csv').open(encoding='utf-8-sig')))
            result = task['state']['result']
            index = result['columns'].index(task['state']['plan']['chart']['y'])
            actual = sum(Decimal(str(row[index])) for row in result['rows'])
            check(mode + '_sql_correctness', abs(actual - expected) < Decimal('0.01'))
            check(mode + '_report', client.get('/api/tasks/' + task_id + '/report').status_code == 200)
            stream = client.get('/api/tasks/' + task_id + '/events').text
            check(mode + '_event_replay', 'event: trace' in stream and 'event: settled' in stream)
            return task

        run_task('demo')
        if args.live:
            check('live_model_configured', health['live_configured'])
            live_task = run_task('live')
            check('live_usage_recorded', bool(live_task['state']['usage']))

        content = Path('docs/COMPANY_VISUALS.md').read_bytes()
        uploaded = client.post('/api/knowledge', files={'file': ('company-reference.md', content)})
        uploaded.raise_for_status()
        doc = uploaded.json()
        try:
            hits = client.get('/api/knowledge/search', params={'q': '钛钢复合材料'}).json()['results']
            check('document_retrieval', any(h['document_id'] == doc['id'] for h in hits))
            if args.live:
                answer = client.get('/api/knowledge/answer', params={'q': '公开资料中的产品系列有哪些？'}).json()
                check('grounded_model_answer', bool(answer['answer']) and bool(answer['citations']))
        finally:
            check('document_delete', client.delete('/api/knowledge/' + doc['id']).status_code == 200)
        check('deleted_document_absent', all(d['id'] != doc['id'] for d in client.get('/api/knowledge').json()))

    # Controlled vectors verify the real Qdrant service, independently of an embedding provider.
    from app.vector_store import QdrantIndex

    async def vector_checks():
        index = QdrantIndex()
        check('qdrant_enabled', index.enabled)
        a, b = uuid.uuid4().hex, uuid.uuid4().hex
        model = 'acceptance-controlled-vectors'
        try:
            await index.upsert([{'id': a, 'vector': [1., 0., 0.]}], model, 'acceptance-a')
            await index.upsert([{'id': b, 'vector': [1., 0., 0.]}], model, 'acceptance-b')
            hits = await index.search([1., 0., 0.], model, 'acceptance-a')
            check('qdrant_real_search_and_tenant_filter', a in dict(hits) and b not in dict(hits))
            await index.delete([a], model, 3)
            check('qdrant_real_delete', a not in dict(await index.search([1., 0., 0.], model, 'acceptance-a')))
        finally:
            await index.delete([a, b], model, 3)

    asyncio.run(vector_checks())
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO
    from app.knowledge import _extract_text

    image = Image.new('RGB', (1500, 300), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=60)
    draw.text((50, 80), 'ARCHIVE MATERIAL QUALITY 2026', fill='black', font=font)
    raw = BytesIO()
    image.save(raw, format='PNG')
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=750, height=150)
        page.insert_image(page.rect, stream=raw.getvalue())
        extracted = _extract_text('scanned.pdf', pdf.tobytes())
    check('real_scanned_pdf_ocr', 'MATERIAL' in extracted[0][1].upper())
    evidence = {'passed': sum(r['passed'] for r in results), 'total': len(results),
                'checks': results, 'live': args.live}
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Verify persisted reports survive an actual application container restart."""
import json
import subprocess
import time
from pathlib import Path

import httpx


def main():
    with httpx.Client(base_url='http://127.0.0.1:8203', timeout=10, trust_env=False) as client:
        before = client.get('/api/tasks').json()
        task_id = next(t['id'] for t in before if t['status'] == 'completed')
        subprocess.run(['docker', 'compose', 'restart', 'app'], check=True)
        deadline = time.monotonic() + 60
        while True:
            try:
                if client.get('/api/health').status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError('Application not ready after restart')
            time.sleep(0.5)
        after = client.get('/api/tasks').json()
        report = client.get('/api/tasks/' + task_id + '/report')
        passed = len(before) == len(after) and report.status_code == 200
        result = {'tasks_before': len(before), 'tasks_after': len(after),
                  'preserved_task': task_id, 'report_status': report.status_code,
                  'passed': passed}
        Path('docs/verification/restart.json').write_text(
            json.dumps(result, indent=2), encoding='utf-8')
        assert passed, result
        print(json.dumps(result))


if __name__ == '__main__':
    main()

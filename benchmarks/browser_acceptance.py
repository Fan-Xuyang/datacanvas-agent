"""Verify user-visible analysis and responsive layout using installed Chrome."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            headless=True,
        )
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8203/', wait_until='networkidle')
        page.locator('#query').fill('按月份查看销售额趋势')
        page.get_by_role('button', name='生成分析 ↗').click()
        page.locator('.task-status .pill.completed').wait_for(timeout=60000)
        assert page.locator('.results tbody tr').count() > 0
        assert page.locator('.results pre').count() > 0
        assert page.locator('.trace li').count() > 0
        with page.expect_download() as download_info:
            page.get_by_role('button', name='下载 CSV').click()
        download = download_info.value
        assert download.suggested_filename.endswith('.csv')
        assert 'category' in Path(download.path()).read_text(encoding='utf-8-sig')
        page.get_by_role('button', name='钛-钢复合材料', exact=False).click()
        assert '钛-钢复合材料' in page.get_by_role('textbox', name='知识库问题').input_value()
        output = Path('docs/verification')
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(output / 'mobile.png'), full_page=True)
        overflow = page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        browser.close()
        assert not errors, errors
        assert not overflow, 'Mobile layout exceeds viewport width'
        result = {'analysis_completed': True, 'sql_visible': True, 'table_visible': True,
                  'trace_visible': True, 'material_knowledge_navigation': True,
                  'csv_download_verified': True,
                  'mobile_no_overflow': True, 'javascript_errors': errors}
        (output / 'browser.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))


if __name__ == '__main__':
    main()

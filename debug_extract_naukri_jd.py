import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

from config import Config


JOB_URL = "https://www.naukri.com/job-listings-azure-devops-engineer-globant-hyderabad-pune-bengaluru-6-to-11-years-030726012322"
OUTPUT_PATH = Path(__file__).with_name("debug_extract_naukri_jd_results.json")


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def preview(text: str) -> str:
    text = clean_text(text)
    return text[:240]


async def run_strategy(page, label: str, script: str):
    try:
        value = await page.evaluate(script)
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        normalized = clean_text(value)
        return {
            "label": label,
            "success": len(normalized) > 120,
            "length": len(normalized),
            "preview": preview(normalized),
            "text": normalized,
        }
    except Exception as exc:
        return {
            "label": label,
            "success": False,
            "length": 0,
            "preview": "",
            "text": "",
            "error": str(exc),
        }


STRATEGIES = [
    (
        "1_json_ld_direct",
        """() => {
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const data = JSON.parse(s.textContent);
                    if (data.description) return data.description;
                } catch (e) {}
            }
            return '';
        }""",
    ),
    (
        "2_json_ld_graph",
        """() => {
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const data = JSON.parse(s.textContent);
                    const graph = data['@graph'] || data.graph || [];
                    for (const item of graph) {
                        if (item && item.description) return item.description;
                    }
                } catch (e) {}
            }
            return '';
        }""",
    ),
    (
        "3_meta_description",
        """() => {
            const meta = document.querySelector('meta[name="description"]');
            return meta ? meta.content : '';
        }""",
    ),
    (
        "4_job_desc_section",
        """() => {
            const el = document.querySelector('section[class*="job-desc"]');
            return el ? el.innerText : '';
        }""",
    ),
    (
        "5_job_desc_div",
        """() => {
            const el = document.querySelector('div[class*="job-desc"]');
            return el ? el.innerText : '';
        }""",
    ),
    (
        "6_styles_jdc_div",
        """() => {
            const el = document.querySelector('div[class*="styles_JDC"]');
            return el ? el.innerText : '';
        }""",
    ),
    (
        "7_jdc_section",
        """() => {
            const el = document.querySelector('section[class*="JDC"]');
            return el ? el.innerText : '';
        }""",
    ),
    (
        "8_dang_inner_html",
        """() => {
            const el = document.querySelector('div[class*="dang-inner-html"]');
            return el ? el.innerText : '';
        }""",
    ),
    (
        "9_job_description_id",
        """() => {
            const el = document.querySelector('#job_description');
            return el ? el.innerText : '';
        }""",
    ),
    (
        "10_job_description_class",
        """() => {
            const el = document.querySelector('.job-description');
            return el ? el.innerText : '';
        }""",
    ),
    (
        "11_article_main",
        """() => {
            const el = document.querySelector('main article, main section, article');
            return el ? el.innerText : '';
        }""",
    ),
    (
        "12_heading_following_block",
        """() => {
            const headings = [...document.querySelectorAll('h1,h2,h3,h4')];
            for (const heading of headings) {
                const t = (heading.innerText || '').toLowerCase();
                if (t.includes('job description') || t.includes('role') || t.includes('about the job')) {
                    let node = heading.nextElementSibling;
                    const chunks = [];
                    while (node && chunks.join(' ').length < 8000) {
                        const txt = (node.innerText || '').trim();
                        if (txt) chunks.push(txt);
                        if (chunks.join(' ').length > 400) break;
                        node = node.nextElementSibling;
                    }
                    return chunks.join('\n');
                }
            }
            return '';
        }""",
    ),
    (
        "13_largest_semantic_block",
        """() => {
            const candidates = document.querySelectorAll('section, div, article');
            let best = '';
            let bestLen = 0;
            for (const el of candidates) {
                const text = (el.innerText || '').trim();
                const lc = text.toLowerCase();
                const ok = text.length > 500 && text.length < 15000 && (
                    lc.includes('responsibilities') || lc.includes('requirements') || lc.includes('qualification') ||
                    lc.includes('job description') || lc.includes('experience') || lc.includes('skills')
                );
                if (!ok) continue;
                const cls = (el.className || '').toLowerCase();
                if (cls.includes('footer') || cls.includes('header') || cls.includes('sidebar') || cls.includes('recommend')) continue;
                if (text.length > bestLen) {
                    best = text;
                    bestLen = text.length;
                }
            }
            return best;
        }""",
    ),
    (
        "14_dom_text_near_skills",
        """() => {
            const all = [...document.querySelectorAll('section, div')];
            for (const el of all) {
                const text = (el.innerText || '').trim();
                const lc = text.toLowerCase();
                if (lc.includes('key skills') && text.length > 300) {
                    return text;
                }
            }
            return '';
        }""",
    ),
    (
        "15_script_jobdescription_regex",
        """() => {
            const scripts = [...document.scripts];
            for (const script of scripts) {
                const text = script.textContent || '';
                const match = text.match(/"jobDescription"\\s*:\\s*"([\\s\\S]*?)"/);
                if (match) return match[1];
            }
            return '';
        }""",
    ),
    (
        "16_script_description_regex",
        """() => {
            const scripts = [...document.scripts];
            for (const script of scripts) {
                const text = script.textContent || '';
                const match = text.match(/"description"\\s*:\\s*"([\\s\\S]{200,5000}?)"/);
                if (match) return match[1];
            }
            return '';
        }""",
    ),
    (
        "17_next_data_search",
        """() => {
            const next = document.querySelector('#__NEXT_DATA__');
            if (!next) return '';
            try {
                const data = JSON.parse(next.textContent);
                const queue = [data];
                while (queue.length) {
                    const item = queue.shift();
                    if (!item) continue;
                    if (typeof item === 'string') continue;
                    if (Array.isArray(item)) {
                        queue.push(...item);
                        continue;
                    }
                    if (item.jobDescription) return item.jobDescription;
                    if (item.description && typeof item.description === 'string' && item.description.length > 200) return item.description;
                    queue.push(...Object.values(item));
                }
            } catch (e) {}
            return '';
        }""",
    ),
    (
        "18_window_data_search",
        """() => {
            const roots = [window.__NEXT_DATA__, window.__INITIAL_STATE__, window.__PRELOADED_STATE__, window.__NUXT__];
            for (const root of roots) {
                if (!root) continue;
                const queue = [root];
                while (queue.length) {
                    const item = queue.shift();
                    if (!item || typeof item === 'string') continue;
                    if (Array.isArray(item)) {
                        queue.push(...item);
                        continue;
                    }
                    if (item.jobDescription) return item.jobDescription;
                    if (item.description && typeof item.description === 'string' && item.description.length > 200) return item.description;
                    queue.push(...Object.values(item));
                }
            }
            return '';
        }""",
    ),
    (
        "19_accessibility_regions",
        """() => {
            const regions = document.querySelectorAll('[role="main"], [role="region"], main');
            let best = '';
            for (const el of regions) {
                const text = (el.innerText || '').trim();
                if (text.length > best.length) best = text;
            }
            return best;
        }""",
    ),
    (
        "20_body_text_filtered",
        """() => {
            const text = (document.body && document.body.innerText) || '';
            const lines = text.split('\n').map(x => x.trim()).filter(Boolean);
            const kept = [];
            for (const line of lines) {
                const lc = line.toLowerCase();
                if (lc.includes('register now') || lc.includes('recommended jobs') || lc.includes('similar jobs')) continue;
                kept.push(line);
            }
            return kept.join('\n');
        }""",
    ),
]


async def main():
    results = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=Config.BROWSER_DATA_DIR,
            headless=False,
            viewport={"width": 1440, "height": 1000},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(JOB_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(4000)

        for scroll_y in [400, 900, 1400, 2000, 2600]:
            await page.evaluate(f"window.scrollTo(0, {scroll_y})")
            await page.wait_for_timeout(800)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)

        page_title = await page.title()
        current_url = page.url

        print(f"PAGE_TITLE: {page_title}")
        print(f"FINAL_URL: {current_url}")

        for label, script in STRATEGIES:
            result = await run_strategy(page, label, script)
            results.append(result)
            status = "SUCCESS" if result["success"] else "MISS"
            print(f"{label}: {status} len={result['length']} preview={result['preview']}")

        await context.close()

    payload = {
        "job_url": JOB_URL,
        "page_title": page_title,
        "final_url": current_url,
        "results": results,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE_RESULTS: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
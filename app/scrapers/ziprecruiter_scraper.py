"""ZipRecruiter (International Remote) job search scraper via persistent Playwright browser."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from urllib.parse import urlencode

from app import database as db
from app.ai_engine import ai_engine
from app.browser_manager import browser_manager


async def search_ziprecruiter_jobs(
    keywords: list[str],
    max_per_query: int = 10,
) -> list[int]:
    """
    Search ZipRecruiter for Remote international roles matching keywords.
    Enforces remote-only since ZipRecruiter is US/International (P3 priority).
    """
    page = await browser_manager.get_active_page(bring_to_front=False)
    saved_ids: list[int] = []

    for kw in keywords:
        if browser_manager.search_limit_reached():
            break
        await browser_manager.update_search_progress(current_platform="ZipRecruiter (Intl Remote)", current_query=f"'{kw}'")
        params = {
            "search": kw,
            "location": "Remote",
            "refine_by_location_type": "only_remote",
        }
        url = f"https://www.ziprecruiter.com/jobs-search?{urlencode(params)}"
        await browser_manager.log(f"ZipRecruiter (Intl Remote) search: '{kw}'...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3.0)
        except Exception as exc:
            await browser_manager.log(f"ZipRecruiter navigation error: {type(exc).__name__}: {exc}", level="warning")
            continue

        # Check for human verification / login wall
        title_low = (await page.title()).lower()
        if any(k in title_low for k in ("just a moment", "verify", "access denied", "captcha")) or await page.locator("iframe[src*='captcha'], iframe[src*='turnstile']").count() > 0:
            decision = await browser_manager.request_human_action(
                reason="ZipRecruiter showed a verification or login screen. Complete it in the browser window, then click Resume.",
                url=page.url,
                job_title=f"ZipRecruiter Search: {kw}",
            )
            if decision in ("skip", "abort"):
                return saved_ids
            await asyncio.sleep(2.0)

        cards = await page.evaluate(
            """
            (maxItems) => {
              const articles = Array.from(document.querySelectorAll('article, div[data-testid="job-card"], section.job_result'));
              const out = [];
              const seen = new Set();
              for (const el of articles) {
                const link = el.querySelector('a[href*="/c/"], a[href*="/jobs/"], a[data-testid="job-title"], h2 a');
                if (!link) continue;
                const href = link.href || '';
                if (!href || seen.has(href)) continue;
                seen.add(href);
                const title = (link.innerText || el.querySelector('h2')?.innerText || '').trim();
                if (!title) continue;
                const company = (el.querySelector('[data-testid="job-card-company"], a[data-testid="company-name"], .company_name')?.innerText || '').trim();
                const location = (el.querySelector('[data-testid="job-card-location"], .location')?.innerText || 'Remote (International)').trim();
                const snippet = (el.innerText || '').trim().slice(0, 1200);
                out.push({ url: href, title, company, location, snippet });
                if (out.length >= maxItems) break;
              }
              return out;
            }
            """,
            max_per_query,
        )

        await browser_manager.log(f"Found {len(cards or [])} ZipRecruiter listings for '{kw}'. Analyzing...")
        for c in cards or []:
            if browser_manager.search_limit_reached():
                return saved_ids
            try:
                ext_id = hashlib.md5(c["url"].encode("utf-8")).hexdigest()[:16]
                raw_job: dict[str, Any] = {
                    "source": "ziprecruiter",
                    "external_id": ext_id,
                    "title": c["title"],
                    "company": c["company"],
                    "location": c["location"] if "remote" in c["location"].lower() else f"{c['location']} (Remote)",
                    "work_mode": "remote",
                    "is_international": True,
                    "apply_type": "external",
                    "url": c["url"],
                    "external_apply_url": c["url"],
                    "description": c["snippet"],
                }
                analysis = await ai_engine.analyze_job(raw_job)
                analysis["work_mode"] = "remote"
                raw_job.update(analysis)
                job_id = await db.upsert_job(raw_job)
                saved_ids.append(job_id)
                await browser_manager.update_search_progress(increment=1)
                await browser_manager.emit("job_added", {"job_id": job_id, "title": c["title"], "score": raw_job["match_score"]})
            except Exception as exc:
                await browser_manager.log(f"Skipped ZipRecruiter job: {type(exc).__name__}: {exc}", level="warning")

    await browser_manager.log(f"ZipRecruiter search finished. Indexed {len(saved_ids)} jobs.")
    return saved_ids

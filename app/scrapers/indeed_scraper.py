"""Indeed Brazil job search scraper using the persistent Playwright Chromium browser."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from app import database as db
from app.ai_engine import ai_engine
from app.browser_manager import browser_manager


async def search_indeed_jobs(
    keywords: list[str],
    locations: list[str],
    max_per_query: int = 10,
) -> list[int]:
    """Search Indeed Brazil (br.indeed.com) and Indeed International Remote (www.indeed.com)."""
    page = await browser_manager.get_active_page(bring_to_front=False)
    saved_ids: list[int] = []

    br_locations = [l for l in locations if any(k in l.lower() for k in ("são paulo", "sao paulo", "cotia", "brazil", "brasil"))]
    if not br_locations:
        br_locations = ["São Paulo, SP"]
    has_intl = any(
        not any(k in l.lower() for k in ("são paulo", "sao paulo", "cotia", "brazil", "brasil"))
        for l in locations
    )

    search_targets: list[tuple[str, str, bool]] = [
        ("https://br.indeed.com", loc, False) for loc in br_locations[:2]
    ]
    if has_intl:
        search_targets.append(("https://www.indeed.com", "Remote", True))

    for kw in keywords:
        if browser_manager.search_limit_reached():
            break
        for base_url, loc, is_intl in search_targets:
            if browser_manager.search_limit_reached():
                break
            params = {"q": kw, "l": loc}
            if is_intl:
                params["sc"] = "0kf:attr(DSQF7);"
            url = f"{base_url}/jobs?{urlencode(params)}"
            label = "Indeed (Intl Remote)" if is_intl else "Indeed Brazil"
            await browser_manager.update_search_progress(current_platform=label, current_query=f"'{kw}' ({loc})")
            await browser_manager.log(f"{label} search: '{kw}' in '{loc}'...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2.5)
            except Exception as exc:
                await browser_manager.log(f"{label} navigation error: {type(exc).__name__}: {exc}", level="warning")
                continue

            # Pause if Indeed shows a human verification check
            page_title = (await page.title()).lower()
            if "just a moment" in page_title or "verify" in page_title or await page.locator("iframe[src*='turnstile'], iframe[src*='captcha']").count() > 0:
                decision = await browser_manager.request_human_action(
                    reason=f"{label} showed a human verification check. Please complete it in the browser window, then click Resume.",
                    url=page.url,
                    job_title=f"{label}: {kw}",
                )
                if decision in ("skip", "abort"):
                    return saved_ids
                await asyncio.sleep(2.0)

            cards = await page.evaluate(
                """
                ([maxItems, baseUrl]) => {
                  const items = Array.from(document.querySelectorAll('div.job_seen_beacon, td.resultContent'));
                  const out = [];
                  const seen = new Set();
                  for (const el of items) {
                    const link = el.querySelector('a[data-jk], h2.jobTitle a');
                    if (!link) continue;
                    const jk = link.getAttribute('data-jk') || (link.href.match(/jk=([a-zA-Z0-9]+)/) || [])[1] || '';
                    if (!jk || seen.has(jk)) continue;
                    seen.add(jk);
                    const title = (link.innerText || '').trim();
                    const company = (el.querySelector('[data-testid="company-name"], .companyName')?.innerText || '').trim();
                    const location = (el.querySelector('[data-testid="text-location"], .companyLocation')?.innerText || '').trim();
                    const snippet = (el.querySelector('.job-snippet, ul')?.innerText || '').trim();
                    out.push({ jk, title, company, location, snippet, url: `${baseUrl}/viewjob?jk=${jk}` });
                    if (out.length >= maxItems) break;
                  }
                  return out;
                }
                """,
                [max_per_query, base_url],
            )

            await browser_manager.log(f"Found {len(cards or [])} {label} listings for '{kw}' ({loc}). Analyzing...")
            for c in cards or []:
                if browser_manager.search_limit_reached():
                    return saved_ids
                try:
                    raw_job: dict[str, Any] = {
                        "source": "indeed",
                        "external_id": c["jk"],
                        "title": c["title"],
                        "company": c["company"],
                        "location": c["location"] or loc,
                        "is_international": is_intl,
                        "apply_type": "external",
                        "url": c["url"],
                        "external_apply_url": c["url"],
                        "description": c["snippet"],
                    }
                    if is_intl:
                        raw_job["work_mode"] = "remote"
                    analysis = await ai_engine.analyze_job(raw_job)
                    if is_intl:
                        analysis["work_mode"] = "remote"
                    raw_job.update(analysis)
                    job_id = await db.upsert_job(raw_job)
                    saved_ids.append(job_id)
                    await browser_manager.update_search_progress(increment=1)
                    await browser_manager.emit("job_added", {"job_id": job_id, "title": c["title"], "score": raw_job["match_score"]})
                except Exception as exc:
                    await browser_manager.log(f"Skipped Indeed job: {type(exc).__name__}: {exc}", level="warning")

    await browser_manager.log(f"Indeed search finished. Indexed {len(saved_ids)} jobs.")
    return saved_ids

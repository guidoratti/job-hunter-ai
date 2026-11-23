"""Glassdoor (Brazil & International Remote) job search scraper via persistent Playwright browser."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from urllib.parse import urlencode

from app import database as db
from app.ai_engine import ai_engine
from app.browser_manager import browser_manager


async def search_glassdoor_jobs(
    keywords: list[str],
    locations: list[str],
    max_per_query: int = 10,
) -> list[int]:
    """
    Search Glassdoor Brazil (glassdoor.com.br) for São Paulo / Cotia / Remote roles,
    and Glassdoor International (glassdoor.com) for Remote roles if international locations are included.
    """
    page = await browser_manager.get_active_page(bring_to_front=False)
    saved_ids: list[int] = []

    has_intl = any(
        not any(k in l.lower() for k in ("são paulo", "sao paulo", "cotia", "brazil", "brasil"))
        for l in locations
    )

    targets = [("https://www.glassdoor.com.br/Job/jobs.htm", "São Paulo, Brasil", False)]
    if has_intl:
        targets.append(("https://www.glassdoor.com/Job/jobs.htm", "Remote (International)", True))

    for base_url, default_loc, is_intl in targets:
        if browser_manager.search_limit_reached():
            break
        for kw in keywords:
            if browser_manager.search_limit_reached():
                break
            params: dict[str, str] = {"sc.keyword": kw}
            if is_intl:
                params["remoteWorkType"] = "1"
            url = f"{base_url}?{urlencode(params)}"
            label = "Glassdoor (Intl Remote)" if is_intl else "Glassdoor Brasil"
            await browser_manager.update_search_progress(current_platform=label, current_query=f"'{kw}'")
            await browser_manager.log(f"{label} search: '{kw}'...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(3.0)
            except Exception as exc:
                await browser_manager.log(f"{label} navigation error: {type(exc).__name__}: {exc}", level="warning")
                continue

            # Detect login modal / verification check
            title_low = (await page.title()).lower()
            if (
                any(k in title_low for k in ("just a moment", "verify", "security", "captcha"))
                or any(k in page.url.lower() for k in ("/profile/login", "/member/home/login"))
                or await page.locator("iframe[src*='captcha'], iframe[src*='turnstile']").count() > 0
            ):
                decision = await browser_manager.request_human_action(
                    reason=f"{label} requires sign-in or verification. Complete it in the browser window, then click Resume.",
                    url=page.url,
                    job_title=f"{label}: {kw}",
                )
                if decision in ("skip", "abort"):
                    return saved_ids
                await asyncio.sleep(2.0)

            cards = await page.evaluate(
                """
                (maxItems) => {
                  const items = Array.from(document.querySelectorAll('li[data-test="jobListing"], div[data-test="jobListing"], article[data-test="jobListing"]'));
                  const out = [];
                  const seen = new Set();
                  for (const el of items) {
                    const link = el.querySelector('a[data-test="job-title"], a[href*="/job-listing/"], a[href*="/partner/jobListing"]');
                    if (!link) continue;
                    const href = link.href || '';
                    if (!href || seen.has(href)) continue;
                    seen.add(href);
                    const title = (link.innerText || '').trim();
                    if (!title) continue;
                    const company = (el.querySelector('[class*="EmployerProfile_compactEmployerName"], [data-test="employer-short-name"], .job-search-key-l2wjgv')?.innerText || '').trim();
                    const location = (el.querySelector('[data-test="emp-location"]')?.innerText || '').trim();
                    const salary = (el.querySelector('[data-test="detailSalary"]')?.innerText || '').trim();
                    const snippet = (el.innerText || '').trim().slice(0, 1200);
                    out.push({ url: href, title, company, location, salary, snippet });
                    if (out.length >= maxItems) break;
                  }
                  return out;
                }
                """,
                max_per_query,
            )

            await browser_manager.log(f"Found {len(cards or [])} {label} listings for '{kw}'. Analyzing...")
            for c in cards or []:
                if browser_manager.search_limit_reached():
                    return saved_ids
                try:
                    ext_id = hashlib.md5(c["url"].encode("utf-8")).hexdigest()[:16]
                    desc = c["snippet"]
                    if c.get("salary"):
                        desc = f"Glassdoor Salary Estimate: {c['salary']}\n\n{desc}"
                    raw_job: dict[str, Any] = {
                        "source": "glassdoor",
                        "external_id": ext_id,
                        "title": c["title"],
                        "company": c["company"],
                        "location": c["location"] or default_loc,
                        "is_international": is_intl,
                        "apply_type": "external",
                        "url": c["url"],
                        "external_apply_url": c["url"],
                        "description": desc,
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
                    await browser_manager.log(f"Skipped Glassdoor job: {type(exc).__name__}: {exc}", level="warning")

    await browser_manager.log(f"Glassdoor search finished. Indexed {len(saved_ids)} jobs.")
    return saved_ids

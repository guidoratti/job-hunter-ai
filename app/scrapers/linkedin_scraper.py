"""LinkedIn Jobs scraper using the persistent interactive Chromium browser."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from app import database as db
from app.ai_engine import ai_engine
from app.browser_manager import browser_manager


async def search_linkedin_jobs(
    keywords: list[str],
    locations: list[str],
    work_modes: list[str] | None = None,
    easy_apply_only: bool = False,
    max_per_query: int = 12,
) -> list[int]:
    """
    Search LinkedIn Jobs for each (keyword, location) pair, extract full JDs,
    score them with Gemini AI, and save to SQLite. Returns list of saved job IDs.
    """
    page = await browser_manager.get_active_page()
    saved_ids: list[int] = []

    # Map work modes to LinkedIn f_WT codes: 1=On-site, 2=Remote, 3=Hybrid
    wt_map = {"onsite": "1", "remote": "2", "hybrid": "3"}
    wt_codes = [wt_map[m] for m in (work_modes or ["hybrid", "remote"]) if m in wt_map]

    for kw in keywords:
        if browser_manager.search_limit_reached():
            break
        for loc in locations:
            if browser_manager.search_limit_reached():
                break
            await browser_manager.update_search_progress(
                current_platform="LinkedIn",
                current_query=f"'{kw}' ({loc})",
            )
            params: dict[str, str] = {
                "keywords": kw,
                "location": loc,
                "sortBy": "R",
            }
            # For international searches, enforce Remote only (f_WT=2)
            loc_low = loc.lower()
            is_brazil_query = any(k in loc_low for k in ("brazil", "brasil", "são paulo", "sao paulo", "cotia"))
            if not is_brazil_query:
                params["f_WT"] = "2"
            elif wt_codes:
                params["f_WT"] = ",".join(wt_codes)

            if easy_apply_only:
                params["f_AL"] = "true"

            search_url = f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"
            await browser_manager.log(f"LinkedIn search: '{kw}' in '{loc}'...")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.5)

            # Check if login / authwall / challenge is blocking access
            if any(token in page.url.lower() for token in ("/login", "/authwall", "/checkpoint", "/uas/")):
                decision = await browser_manager.request_human_action(
                    reason="LinkedIn requires you to sign in (or complete security verification) in the browser window.",
                    url=page.url,
                    job_title=f"LinkedIn Search: {kw}",
                )
                if decision in ("skip", "abort"):
                    return saved_ids
                await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2.5)

            # Wait briefly for job cards to render (handles both logged-in & public LinkedIn layouts)
            try:
                await page.wait_for_selector(
                    "li[data-occludable-job-id], div[data-job-id], ul.jobs-search__results-list li, a[href*='/jobs/view/']",
                    timeout=8000,
                )
            except Exception:
                pass

            # Collect job cards from the left rail (supports authenticated + guest layouts)
            card_selectors = [
                "li.scaffold-layout__list-item[data-occludable-job-id]",
                "div.job-card-container[data-job-id]",
                "li[data-occludable-job-id]",
                "div.base-card[data-entity-urn]",
                "ul.jobs-search__results-list li",
                "a[href*='/jobs/view/']",
            ]
            cards = None
            for sel in card_selectors:
                loc_cards = page.locator(sel)
                if await loc_cards.count() > 0:
                    cards = loc_cards
                    break

            if cards is None:
                await browser_manager.log(f"No LinkedIn job cards found for '{kw}' in '{loc}' (URL: {page.url[:65]}).", level="warning")
                continue

            total = min(await cards.count(), max_per_query)
            await browser_manager.log(f"Found {total} LinkedIn listings for '{kw}' ({loc}). Analyzing...")

            for idx in range(total):
                if browser_manager.search_limit_reached():
                    await browser_manager.log("Reached search cap. Stopping search.")
                    return saved_ids
                try:
                    card = cards.nth(idx)
                    await card.scroll_into_view_if_needed()
                    card_text = (await card.inner_text()).strip()
                    await card.click(timeout=5000)
                    await asyncio.sleep(1.5)

                    # Extract job ID from attributes, URN, link href, or page URL
                    ext_id = (
                        await card.get_attribute("data-occludable-job-id")
                        or await card.get_attribute("data-job-id")
                        or ""
                    )
                    if not ext_id:
                        urn = await card.get_attribute("data-entity-urn") or ""
                        m_urn = re.search(r"(\d+)$", urn)
                        if m_urn:
                            ext_id = m_urn.group(1)
                    if not ext_id:
                        href = await card.get_attribute("href") or ""
                        if not href:
                            link_el = card.locator("a[href*='/jobs/view/']").first
                            if await link_el.count() > 0:
                                href = await link_el.get_attribute("href") or ""
                        m_href = re.search(r"/jobs/view/(?:[^/?]+-)?(\d+)", href)
                        if m_href:
                            ext_id = m_href.group(1)
                    if not ext_id:
                        m = re.search(r"currentJobId=(\d+)", page.url)
                        if m:
                            ext_id = m.group(1)
                    if not ext_id:
                        continue

                    job_url = f"https://www.linkedin.com/jobs/view/{ext_id}/"

                    # Extract title, company, location, description from detail pane (with card fallback)
                    title = ""
                    for t_sel in (
                        ".job-details-jobs-unified-top-card__job-title h1",
                        ".job-details-jobs-unified-top-card__job-title",
                        "h1.t-24",
                        "h2.top-card-layout__title",
                    ):
                        el = page.locator(t_sel).first
                        if await el.count() > 0:
                            title = (await el.inner_text()).strip()
                            if title:
                                break
                    if not title and card_text:
                        title = card_text.splitlines()[0].strip()

                    company = ""
                    for c_sel in (
                        ".job-details-jobs-unified-top-card__company-name",
                        ".jobs-unified-top-card__company-name",
                        "a.topcard__org-name-link",
                    ):
                        el = page.locator(c_sel).first
                        if await el.count() > 0:
                            company = (await el.inner_text()).strip()
                            if company:
                                break
                    if not company and len(card_text.splitlines()) > 1:
                        company = card_text.splitlines()[1].strip()

                    job_loc = loc
                    for l_sel in (
                        ".job-details-jobs-unified-top-card__primary-description-container",
                        ".job-details-jobs-unified-top-card__tertiary-description-container",
                        "span.topcard__flavor--bullet",
                    ):
                        el = page.locator(l_sel).first
                        if await el.count() > 0:
                            raw_loc = (await el.inner_text()).strip()
                            if raw_loc:
                                job_loc = raw_loc.split("·")[0].strip()
                                break

                    description = ""
                    for d_sel in ("#job-details", ".jobs-description__content", ".jobs-box__html-content", ".show-more-less-html__markup"):
                        el = page.locator(d_sel).first
                        if await el.count() > 0:
                            description = (await el.inner_text()).strip()
                            if description:
                                break
                    if not description:
                        description = card_text

                    # Detect Easy Apply vs External Apply
                    apply_type = "external"
                    easy_btn = page.locator("button.jobs-apply-button").first
                    if await easy_btn.count() > 0:
                        btn_text = (await easy_btn.inner_text()).lower()
                        if any(k in btn_text for k in ("easy apply", "candidatura simplificada", "candidatura semplice")):
                            apply_type = "easy_apply"

                    if not title:
                        continue

                    raw_job: dict[str, Any] = {
                        "source": "linkedin",
                        "external_id": ext_id,
                        "title": title,
                        "company": company,
                        "location": job_loc,
                        "apply_type": apply_type,
                        "url": job_url,
                        "description": description,
                    }

                    analysis = await ai_engine.analyze_job(raw_job)
                    raw_job.update(analysis)
                    job_id = await db.upsert_job(raw_job)
                    saved_ids.append(job_id)
                    await browser_manager.update_search_progress(increment=1)
                    await browser_manager.emit("job_added", {"job_id": job_id, "title": title, "score": raw_job["match_score"]})
                except Exception as exc:
                    await browser_manager.log(f"Skipped LinkedIn card #{idx + 1}: {exc}", level="warning")

    await browser_manager.log(f"LinkedIn search finished. Indexed {len(saved_ids)} jobs.")
    return saved_ids

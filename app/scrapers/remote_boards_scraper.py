"""International Remote job board scraper (Remotive & RemoteOK public JSON feeds)."""

from __future__ import annotations

from typing import Any

import httpx
from bs4 import BeautifulSoup

from app import database as db
from app.ai_engine import ai_engine
from app.browser_manager import browser_manager


def _clean_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


async def search_remote_boards(
    keywords: list[str],
    max_per_query: int = 8,
) -> list[int]:
    """
    Search Remotive public API for international remote roles matching keywords.
    All roles here are 100% remote (fits P3: International Remote priority).
    """
    saved_ids: list[int] = []
    headers = {"User-Agent": "JobHunterAI/1.0"}

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        for kw in keywords:
            if browser_manager.search_limit_reached():
                break
            await browser_manager.update_search_progress(current_platform="Remotive (Intl Remote)", current_query=f"'{kw}'")
            await browser_manager.log(f"Remotive (Intl Remote) search: '{kw}'...")
            try:
                resp = await client.get(
                    "https://remotive.com/api/remote-jobs",
                    params={"search": kw, "limit": max_per_query},
                )
                resp.raise_for_status()
                items = resp.json().get("jobs", [])
            except Exception as exc:
                await browser_manager.log(f"Remotive search error for '{kw}': {type(exc).__name__}: {exc}", level="warning")
                continue

            await browser_manager.log(f"Found {len(items)} Remotive international remote listings for '{kw}'. Analyzing...")
            for item in items[:max_per_query]:
                if browser_manager.search_limit_reached():
                    return saved_ids
                try:
                    ext_id = str(item.get("id", ""))
                    if not ext_id:
                        continue
                    title = str(item.get("title", "")).strip()
                    company = str(item.get("company_name", "")).strip()
                    loc = str(item.get("candidate_required_location", "Worldwide") or "Worldwide").strip()
                    url = str(item.get("url", "")).strip()
                    salary_str = str(item.get("salary", "") or "").strip()
                    desc = _clean_html(str(item.get("description", "")))
                    if salary_str:
                        desc = f"Posted Salary: {salary_str}\n\n{desc}"

                    raw_job: dict[str, Any] = {
                        "source": "remotive",
                        "external_id": ext_id,
                        "title": title,
                        "company": company,
                        "location": f"{loc} (Remote)",
                        "work_mode": "remote",
                        "is_international": True,
                        "apply_type": "external",
                        "url": url,
                        "external_apply_url": url,
                        "description": desc,
                    }

                    analysis = await ai_engine.analyze_job(raw_job)
                    analysis["work_mode"] = "remote"
                    raw_job.update(analysis)

                    job_id = await db.upsert_job(raw_job)
                    saved_ids.append(job_id)
                    await browser_manager.update_search_progress(increment=1)
                    await browser_manager.emit("job_added", {"job_id": job_id, "title": title, "score": raw_job["match_score"]})
                except Exception as exc:
                    await browser_manager.log(f"Skipped Remotive job: {type(exc).__name__}: {exc}", level="warning")

    await browser_manager.log(f"Remotive search finished. Indexed {len(saved_ids)} international remote jobs.")
    return saved_ids

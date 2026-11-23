"""LinkedIn peer-title discovery scraper (strictly capped at 3 minutes) for CV Analysis."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlencode

from app.browser_manager import browser_manager


async def scan_linkedin_peer_titles(
    queries: list[str],
    max_seconds: int = 180,
) -> dict[str, Any]:
    """
    Search LinkedIn People using skill/experience queries derived from the user's CV
    to see what job titles peers with similar backgrounds use.
    Strictly capped at `max_seconds` (default 180s = 3 minutes).
    """
    started = time.time()
    deadline = started + max(15, min(180, int(max_seconds or 180)))
    discovered_headlines: list[str] = []
    seen_low: set[str] = set()
    note = ""

    try:
        page = await browser_manager.get_active_page(bring_to_front=False)
    except Exception as exc:
        return {"headlines": [], "note": f"Browser unavailable for LinkedIn peer scan: {exc}"}

    for q in queries[:4]:
        if time.time() >= deadline:
            note = "Reached 3-minute LinkedIn scan cap."
            break

        url = f"https://www.linkedin.com/search/results/people/?{urlencode({'keywords': q})}"
        await browser_manager.log(f"🔬 CV Analysis: scanning LinkedIn peers for '{q}'...")
        await browser_manager.emit(
            "cv_analysis_progress",
            {
                "active": True,
                "stage": f"Scanning LinkedIn peers: '{q}'",
                "deadline_ts": deadline,
                "found": len(discovered_headlines),
            },
        )
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            await asyncio.sleep(3.0)
        except Exception as exc:
            await browser_manager.log(f"LinkedIn peer scan navigation warning: {exc}", level="warning")
            continue

        # If LinkedIn redirects to login/authwall, don't block the CV analysis — record note and stop peer scan
        if any(tok in page.url.lower() for tok in ("/login", "/authwall", "/checkpoint", "/uas/")):
            note = "LinkedIn sign-in required for live People search (connect LinkedIn SSO in Auto-Fill & Credential Vault for live peer titles)."
            await browser_manager.log(f"🔬 {note}", level="warning")
            break

        try:
            headlines = await page.evaluate(
                """
                () => {
                  const sels = [
                    '.entity-result__primary-subtitle',
                    'div.t-14.t-black.t-normal',
                    'div[class*="entity-result__primary-subtitle"]'
                  ];
                  const found = [];
                  for (const sel of sels) {
                    document.querySelectorAll(sel).forEach(el => {
                      const t = (el.innerText || '').trim();
                      if (t && t.length >= 4 && t.length <= 140) found.push(t);
                    });
                    if (found.length >= 10) break;
                  }
                  return found;
                }
                """
            )
            for h in headlines or []:
                clean = " ".join(str(h).split())
                low = clean.lower()
                if clean and low not in seen_low:
                    seen_low.add(low)
                    discovered_headlines.append(clean)
        except Exception:
            continue

        if len(discovered_headlines) >= 35:
            break

    elapsed = round(time.time() - started, 1)
    await browser_manager.log(
        f"🔬 LinkedIn peer scan finished in {elapsed}s ({len(discovered_headlines)} peer headlines collected)."
    )
    return {"headlines": discovered_headlines[:35], "note": note, "elapsed_seconds": elapsed}

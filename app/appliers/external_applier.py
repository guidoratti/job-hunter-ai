"""External ATS & Gupy application automator with human-in-the-loop roadblock handling."""

from __future__ import annotations

import asyncio
from typing import Any

from app import database as db
from app.ai_engine import ai_engine
from app.appliers.form_filler import (
    detect_login_or_roadblock,
    fill_visible_form_fields,
    upload_matching_resume,
)
from app.browser_manager import browser_manager


async def apply_external_job(
    job: dict[str, Any],
    target_url: str | None = None,
    auto_submit: bool = False,
) -> str:
    """
    Automate application on Gupy or any external ATS (Greenhouse, Lever, Workday, Ashby, etc.).
    Returns final status: 'applied' | 'skipped' | 'needs_action' | 'failed'.
    """
    job_id = job["id"]
    url = target_url or job.get("external_apply_url") or job.get("url")
    title_label = f"{job['title']} @ {job['company']}"

    page = await browser_manager.get_active_page()
    await browser_manager.log(f"Opening external application page: {url}", job_id=job_id)
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(2.5)

    # Click initial landing-page Apply button (Quickin, Gupy, Indeed, Glassdoor, ZipRecruiter, Remotive, Workday, Lever, Greenhouse)
    landing_apply_patterns = (
        "candidatar-se para a vaga",
        "candidatar-se agora",
        "candidatar-se no site da empresa",
        "candidatar-se",
        "quero me candidatar",
        "inscrever-se",
        "apply for this position",
        "apply for this job",
        "apply on company site",
        "apply on employer site",
        "apply now",
        "1-click apply",
        "easy apply",
        "candidati ora",
        "candidati",
        "apply",
    )

    async def _try_click_landing_apply(cur_page):
        # Only skip landing click if an actual application form (3+ visible inputs or a file upload) is already open
        form_inputs = await cur_page.locator("input[type='text']:visible, input[type='email']:visible, input[type='tel']:visible").count()
        file_inputs = await cur_page.locator("input[type='file']").count()
        if form_inputs >= 3 or file_inputs > 0:
            return cur_page, False

        ctx = cur_page.context
        before_pages = list(ctx.pages)
        # Try case-insensitive text match across buttons, links, and role=button (scrolling into view first!)
        for pat in landing_apply_patterns:
            loc = cur_page.locator(f"button:has-text('{pat}'), a:has-text('{pat}'), [role='button']:has-text('{pat}')")
            cnt = await loc.count()
            for idx in range(min(cnt, 5)):
                el = loc.nth(idx)
                try:
                    txt = (await el.inner_text()).strip().lower()
                    if not txt or len(txt) > 45:
                        continue
                    await el.scroll_into_view_if_needed(timeout=3000)
                    if not await el.is_visible():
                        continue
                    await browser_manager.log(f"➡️ Clicking '{txt.title()}' on {cur_page.url[:55]}...", job_id=job_id)
                    try:
                        await el.click(timeout=5000)
                    except Exception:
                        await el.evaluate("node => node.click()")
                    await asyncio.sleep(3.0)
                    new_pages = [p for p in ctx.pages if p not in before_pages and not p.is_closed()]
                    if new_pages:
                        cur_page = new_pages[-1]
                        await cur_page.wait_for_load_state("domcontentloaded", timeout=30000)
                        await asyncio.sleep(2.0)
                    return cur_page, True
                except Exception:
                    continue
        return cur_page, False

    page, _clicked_apply = await _try_click_landing_apply(page)

    # Check for login / account creation / CAPTCHA roadblock
    roadblock = await detect_login_or_roadblock(page)
    if roadblock and "captcha" not in roadblock.lower():
        # Automatically attempt SSO login (LinkedIn first, then Google fallback) before pausing!
        page, sso_ok = await browser_manager.try_auto_sso_login(
            page, preferred_order=("linkedin", "google"), job_id=job_id
        )
        if sso_ok:
            await asyncio.sleep(2.0)
            # Re-check if another landing Apply button appeared after login
            page, _ = await _try_click_landing_apply(page)
            roadblock = await detect_login_or_roadblock(page)

    if roadblock:
        decision = await browser_manager.request_human_action(
            reason=roadblock,
            url=page.url,
            job_id=job_id,
            job_title=title_label,
        )
        if decision == "skip":
            await db.update_job(job_id, status="skipped", status_note="Skipped by user at login/roadblock.")
            return "skipped"
        if decision == "abort":
            return "abort"
        await asyncio.sleep(1.5)

    # Upload language-matched CV and fill visible form fields
    await browser_manager.log(f"📝 Form-Filler Agent uploading CV & filling application fields on {page.url[:60]}...", job_id=job_id)
    cv_uploaded = await upload_matching_resume(page, job)
    filled_count, missing_fields = await fill_visible_form_fields(page, job)

    # If 0 fields were filled and no CV uploaded, we may still be on an unusual landing/redirect page
    if filled_count == 0 and not cv_uploaded and not missing_fields:
        decision = await browser_manager.request_human_action(
            reason="Could not detect an open application form on this page yet. Click the Apply / Candidatar-se button in the browser to open the form, then click Resume so the Form-Filler Agent can fill it!",
            url=page.url,
            job_id=job_id,
            job_title=title_label,
        )
        if decision == "skip":
            await db.update_job(job_id, status="skipped", status_note="Skipped: form not detected.")
            return "skipped"
        if decision == "abort":
            return "abort"
        await asyncio.sleep(1.5)
        cv_uploaded = await upload_matching_resume(page, job)
        filled_count, missing_fields = await fill_visible_form_fields(page, job)

    if missing_fields:
        decision = await browser_manager.request_human_action(
            reason=f"Please complete these fields in the browser window: {', '.join(missing_fields[:6])}. Then submit or click Resume.",
            url=page.url,
            job_id=job_id,
            job_title=title_label,
        )
        if decision == "skip":
            await db.update_job(job_id, status="skipped", status_note="Skipped by user during form fill.")
            return "skipped"
        if decision == "abort":
            return "abort"

    # Always pause for user approval if a Cover/T-Letter was generated/inserted, even when auto_submit is on
    if not auto_submit or job.get("_letter_requires_approval"):
        letter_note = " (Cover Letter generated — please review & approve it before submitting!)" if job.get("_letter_requires_approval") else ""
        decision = await browser_manager.request_human_action(
            reason=f"Filled {filled_count} field(s){' + uploaded CV' if cv_uploaded else ''}{letter_note}. Review in the browser window, click Submit on the site, and then click Resume to mark as Applied.",
            url=page.url,
            job_id=job_id,
            job_title=title_label,
        )
        if decision == "skip":
            await db.update_job(job_id, status="skipped", status_note="Skipped during review.")
            return "skipped"
        if decision == "abort":
            return "abort"
        await db.update_job(job_id, status="applied", status_note="Applied via external ATS (user reviewed).")
        await browser_manager.log(f"Marked as APPLIED: {title_label}", level="success", job_id=job_id)
        return "applied"

    # Best-effort auto-submit on standard ATS buttons
    submit_names = (
        "Submit application",
        "Submit Application",
        "Enviar candidatura",
        "Finalizar candidatura",
        "Invia candidatura",
        "Submit",
        "Apply",
    )
    clicked = False
    for name in submit_names:
        btn = page.get_by_role("button", name=name).first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click()
            clicked = True
            await asyncio.sleep(2.5)
            break

    if not clicked:
        decision = await browser_manager.request_human_action(
            reason="Could not locate a clear final Submit button automatically. Please finish submitting in the browser, then click Resume.",
            url=page.url,
            job_id=job_id,
            job_title=title_label,
        )
        if decision == "skip":
            await db.update_job(job_id, status="skipped", status_note="Skipped at submit.")
            return "skipped"
        if decision == "abort":
            return "abort"

    await db.update_job(job_id, status="applied", status_note="Applied via external ATS.")
    await browser_manager.log(f"Marked as APPLIED: {title_label}", level="success", job_id=job_id)
    return "applied"

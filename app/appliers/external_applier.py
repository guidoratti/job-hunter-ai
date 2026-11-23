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

    # Pre-generate T-Letter & Cover Letter in job's language if not already generated
    if not job.get("generated_cover_letter"):
        try:
            await browser_manager.log(
                f"✍️ Writer Agent drafting tailored T-Letter & Cover Letter ({(job.get('language') or 'pt').upper()}) for {title_label}...",
                job_id=job_id,
            )
            mats = await ai_engine.generate_application_materials(job)
            await db.update_job(
                job_id,
                generated_t_letter=mats["t_letter"],
                generated_cover_letter=mats["cover_letter"],
            )
            job["generated_t_letter"] = mats["t_letter"]
            job["generated_cover_letter"] = mats["cover_letter"]
            await browser_manager.log(f"✍️ Tailored T-Letter & Cover Letter ready for {title_label}.", level="success", job_id=job_id)
        except Exception as exc:
            await browser_manager.log(f"Could not pre-generate letters ({exc}); continuing with form fill.", level="warning", job_id=job_id)

    page = await browser_manager.get_active_page()
    await browser_manager.log(f"Opening external application page: {url}", job_id=job_id)
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(2.5)

    # Click initial landing-page Apply button (Gupy, Indeed, Glassdoor, ZipRecruiter, Remotive, Workday, Lever, Greenhouse)
    landing_apply_texts = (
        "Candidatar-se para a vaga",
        "Candidatar-se agora",
        "Candidatar-se no site da empresa",
        "Candidatar-se",
        "Apply for this position",
        "Apply for this job",
        "Apply on company site",
        "Apply on employer site",
        "Apply now",
        "Apply Now",
        "1-Click Apply",
        "Easy Apply",
        "Candidati ora",
        "Candidati",
        "Apply",
    )
    # Only click a landing Apply button if no application form inputs are visible yet
    visible_form_inputs = await page.locator("input[type='text']:visible, input[type='email']:visible, input[type='file']").count()
    if visible_form_inputs == 0:
        ctx = page.context
        before_pages = list(ctx.pages)
        for btn_text in landing_apply_texts:
            clicked_landing = False
            for role in ("button", "link"):
                el = page.get_by_role(role, name=btn_text).first
                if await el.count() > 0:
                    try:
                        if await el.is_visible():
                            await el.click(timeout=5000)
                            clicked_landing = True
                            await asyncio.sleep(3.0)
                            break
                    except Exception:
                        continue
            if clicked_landing:
                # If clicking opened a new tab (common on Indeed / Glassdoor / Remotive), switch to it
                new_pages = [p for p in ctx.pages if p not in before_pages and not p.is_closed()]
                if new_pages:
                    page = new_pages[-1]
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                    await asyncio.sleep(2.0)
                break

    # Check for login / account creation / CAPTCHA roadblock
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
    await upload_matching_resume(page, job)
    missing_fields = await fill_visible_form_fields(page, job)

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

    if not auto_submit:
        decision = await browser_manager.request_human_action(
            reason="Form auto-filled! Review your application in the browser window, click Submit on the site, and then click Resume to mark as Applied.",
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

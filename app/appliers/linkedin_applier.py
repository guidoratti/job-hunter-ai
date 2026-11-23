"""LinkedIn Easy Apply + External Redirect application automator."""

from __future__ import annotations

import asyncio
from typing import Any

from app import database as db
from app.appliers.external_applier import apply_external_job
from app.appliers.form_filler import (
    detect_login_or_roadblock,
    fill_visible_form_fields,
    upload_matching_resume,
)
from app.browser_manager import browser_manager


async def apply_linkedin_job(job: dict[str, Any], auto_submit: bool = False) -> str:
    """
    Apply to a LinkedIn job.
    - If Easy Apply: automates the multi-step modal with language-matched CV + Gemini Q&A.
    - If External Apply: follows the external link and hands off to `apply_external_job`.
    """
    job_id = job["id"]
    title_label = f"{job['title']} @ {job['company']}"
    page = await browser_manager.get_active_page()

    await browser_manager.log(f"Opening LinkedIn job: {title_label}", job_id=job_id)
    await page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(2.5)

    # Login check
    roadblock = await detect_login_or_roadblock(page)
    if roadblock:
        decision = await browser_manager.request_human_action(
            reason="LinkedIn requires login. Sign in via the browser window (or click Auto-fill Saved Login), then click Resume.",
            url=page.url,
            job_id=job_id,
            job_title=title_label,
        )
        if decision == "skip":
            await db.update_job(job_id, status="skipped", status_note="Skipped at LinkedIn login.")
            return "skipped"
        if decision == "abort":
            return "abort"
        await page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2.5)

    # Wait briefly for LinkedIn's top card & apply button to render
    try:
        await page.wait_for_selector(
            "button.jobs-apply-button, #jobs-apply-button-id, button[aria-label*='Apply' i], button[aria-label*='Candidat' i], a[aria-label*='Apply' i], a[aria-label*='Candidat' i], button.apply-button",
            timeout=8000,
        )
    except Exception:
        pass

    # Check if already applied or closed
    page_body_low = (await page.locator("main, body").first.inner_text()).lower()[:3000]
    if any(k in page_body_low for k in ("no longer accepting applications", "não aceita mais candidaturas", "non accetta più candidature")):
        await db.update_job(job_id, status="skipped", status_note="Job is no longer accepting applications.")
        await browser_manager.log(f"Job closed: {title_label}.", level="warning", job_id=job_id)
        return "skipped"

    apply_selectors = [
        "button.jobs-apply-button:visible",
        "button#jobs-apply-button-id:visible",
        "a.jobs-apply-button:visible",
        "button[aria-label*='Easy Apply' i]:visible",
        "button[aria-label*='Candidatura simplificada' i]:visible",
        "button[aria-label*='Candidatura semplice' i]:visible",
        "button[aria-label*='Apply' i]:visible",
        "button[aria-label*='Candidatar' i]:visible",
        "a[aria-label*='Apply' i]:visible",
        "a[aria-label*='Candidatar' i]:visible",
        "button.apply-button:visible",
        "a.apply-button:visible",
        "main button:has-text('Easy Apply'):visible",
        "main button:has-text('Candidatura simplificada'):visible",
        "main button:has-text('Candidatura semplice'):visible",
        "main button:has-text('Candidatar-se'):visible",
        "main a:has-text('Candidatar-se'):visible",
        "main button:has-text('Apply'):visible",
        "main a:has-text('Apply'):visible",
    ]

    apply_btn = None
    for sel in apply_selectors:
        loc = page.locator(sel).first
        if await loc.count() > 0:
            try:
                if await loc.is_visible():
                    apply_btn = loc
                    break
            except Exception:
                continue

    if apply_btn is None:
        # Pause and let the user inspect / click Apply in the minibrowser rather than failing silently
        decision = await browser_manager.request_human_action(
            reason="Could not automatically locate the LinkedIn Apply button on this page (you may need to sign in or click Apply manually). Click Apply in the browser, then click Resume (or Skip if closed).",
            url=page.url,
            job_id=job_id,
            job_title=title_label,
        )
        if decision == "skip":
            await db.update_job(job_id, status="skipped", status_note="Skipped: Apply button not found.")
            return "skipped"
        if decision == "abort":
            return "abort"
        # After user resumed, check if an Easy Apply modal opened or if we navigated to an external ATS
        if "linkedin.com" not in page.url.lower():
            await db.update_job(job_id, external_apply_url=page.url)
            return await apply_external_job(job, target_url=page.url, auto_submit=auto_submit)
        modal_check = page.locator("div.jobs-easy-apply-modal, div[role='dialog']").first
        if await modal_check.count() == 0:
            await db.update_job(job_id, status="applied", status_note="Completed with user assistance.")
            return "applied"
        is_easy = True
    else:
        btn_text = ((await apply_btn.inner_text()) + " " + (await apply_btn.get_attribute("aria-label") or "")).lower()
        is_easy = any(k in btn_text for k in ("easy apply", "candidatura simplificada", "candidatura semplice"))

    if not is_easy and apply_btn is not None:
        await browser_manager.log(f"External apply detected on LinkedIn for {title_label}. Following external link...", job_id=job_id)
        ctx = page.context
        before_pages = list(ctx.pages)
        href = await apply_btn.get_attribute("href")
        if href and href.startswith("http") and "linkedin.com" not in href.lower():
            await db.update_job(job_id, external_apply_url=href)
            return await apply_external_job(job, target_url=href, auto_submit=auto_submit)

        await apply_btn.click()
        await asyncio.sleep(3.5)

        new_pages = [p for p in ctx.pages if p not in before_pages and not p.is_closed()]
        if new_pages:
            ext_page = new_pages[-1]
            await ext_page.wait_for_load_state("domcontentloaded", timeout=30000)
            ext_url = ext_page.url
            await db.update_job(job_id, external_apply_url=ext_url)
            await ext_page.close()
            return await apply_external_job(job, target_url=ext_url, auto_submit=auto_submit)
        else:
            ext_url = page.url
            if "linkedin.com" not in ext_url.lower():
                await db.update_job(job_id, external_apply_url=ext_url)
                return await apply_external_job(job, target_url=ext_url, auto_submit=auto_submit)
            decision = await browser_manager.request_human_action(
                reason="Clicked External Apply on LinkedIn. Complete any redirect/login in the browser window, then click Resume.",
                url=page.url,
                job_id=job_id,
                job_title=title_label,
            )
            if decision == "skip":
                await db.update_job(job_id, status="skipped", status_note="Skipped external redirect.")
                return "skipped"
            if decision == "abort":
                return "abort"
            if "linkedin.com" not in page.url.lower():
                await db.update_job(job_id, external_apply_url=page.url)
                return await apply_external_job(job, target_url=page.url, auto_submit=auto_submit)
            await db.update_job(job_id, status="applied", status_note="Applied via LinkedIn external link.")
            return "applied"

    # --- LinkedIn Easy Apply Modal Flow ---
    await browser_manager.log(f"Starting LinkedIn Easy Apply for {title_label} ({job['language'].upper()})...", job_id=job_id)
    if apply_btn is not None:
        try:
            await apply_btn.scroll_into_view_if_needed()
            await apply_btn.click(timeout=8000)
        except Exception:
            await apply_btn.evaluate("el => el.click()")
        await asyncio.sleep(2.5)

    modal_selector = (
        "div.jobs-easy-apply-modal:visible, "
        "div[data-test-modal-id='easy-apply-modal']:visible, "
        "div.artdeco-modal[role='dialog']:visible"
    )
    try:
        await page.wait_for_selector(modal_selector, timeout=8000)
    except Exception:
        # Retry click once via JS if modal didn't open on first click
        if apply_btn is not None:
            try:
                await apply_btn.evaluate("el => el.click()")
                await page.wait_for_selector(modal_selector, timeout=6000)
            except Exception:
                pass

    modal = page.locator(modal_selector).first
    if await modal.count() == 0:
        decision = await browser_manager.request_human_action(
            reason="Clicked Easy Apply, but the application modal did not open automatically. Please click 'Candidatura simplificada / Easy Apply' in the browser, then click Resume.",
            url=page.url,
            job_id=job_id,
            job_title=title_label,
        )
        if decision == "skip":
            await db.update_job(job_id, status="skipped", status_note="Skipped: Easy Apply modal did not open.")
            return "skipped"
        if decision == "abort":
            return "abort"
        modal = page.locator(modal_selector).first

    await browser_manager.log(f"📋 LinkedIn Easy Apply modal opened for {title_label}. Navigating steps...", job_id=job_id)

    submit_selectors = [
        "button[aria-label*='Submit application' i]:visible",
        "button[aria-label*='Enviar candidatura' i]:visible",
        "button[aria-label*='Invia candidatura' i]:visible",
        "button:has-text('Enviar candidatura'):visible",
        "button:has-text('Submit application'):visible",
        "button:has-text('Invia candidatura'):visible",
    ]
    next_selectors = [
        "button[aria-label*='Continue to next step' i]:visible",
        "button[aria-label*='Review your application' i]:visible",
        "button[aria-label*='Avançar' i]:visible",
        "button[aria-label*='Revisar' i]:visible",
        "button:has-text('Avançar'):visible",
        "button:has-text('Revisar'):visible",
        "button:has-text('Próximo'):visible",
        "button:has-text('Continuar'):visible",
        "button:has-text('Next'):visible",
        "button:has-text('Review'):visible",
        "button:has-text('Continue'):visible",
        "button:has-text('Avanti'):visible",
        "button:has-text('Rivedi'):visible",
    ]

    async def _find_first(container, selectors: list[str]):
        for sel in selectors:
            loc = container.locator(sel).first
            if await loc.count() > 0:
                try:
                    if await loc.is_visible():
                        return loc
                except Exception:
                    continue
        return None

    max_steps = 12
    for step in range(1, max_steps + 1):
        modal = page.locator(modal_selector).first
        if await modal.count() == 0:
            break

        await browser_manager.log(f"📝 Easy Apply Step {step}: uploading CV & filling fields...", job_id=job_id)

        # Upload language-matched CV if a file input is present on this step
        await upload_matching_resume(page, job, container=modal)

        # Fill visible empty fields with Form-Filler Agent in the job's language
        _filled, missing = await fill_visible_form_fields(page, job, container=modal)
        if missing:
            decision = await browser_manager.request_human_action(
                reason=f"LinkedIn Easy Apply (Step {step}) needs your input for: {', '.join(missing[:5])}. Fill them in the browser, then click Resume.",
                url=page.url,
                job_id=job_id,
                job_title=title_label,
            )
            if decision == "skip":
                await db.update_job(job_id, status="skipped", status_note="Skipped during Easy Apply questions.")
                return "skipped"
            if decision == "abort":
                return "abort"

        # Check for Submit button first (always pause for user approval if a Cover/T-Letter was filled)
        submit_btn = await _find_first(modal, submit_selectors)
        if submit_btn is not None:
            if not auto_submit or job.get("_letter_requires_approval"):
                letter_note = " A Cover Letter was generated — please review & approve it before submitting." if job.get("_letter_requires_approval") else ""
                decision = await browser_manager.request_human_action(
                    reason=f"LinkedIn Easy Apply is ready to submit!{letter_note} Review in the browser, click Submit, then click Resume.",
                    url=page.url,
                    job_id=job_id,
                    job_title=title_label,
                )
                if decision == "skip":
                    await db.update_job(job_id, status="skipped", status_note="Skipped before Easy Apply submit.")
                    return "skipped"
                if decision == "abort":
                    return "abort"
            else:
                await submit_btn.click()
                await asyncio.sleep(2.5)
                # Close "Application sent" confirmation dialog if shown
                dismiss = page.locator("button[aria-label*='Dismiss' i]:visible, button[aria-label*='Fechar' i]:visible").first
                if await dismiss.count() > 0:
                    try:
                        await dismiss.click(timeout=2000)
                    except Exception:
                        pass

            await db.update_job(job_id, status="applied", status_note="Applied via LinkedIn Easy Apply.")
            await browser_manager.log(f"✅ APPLIED (LinkedIn Easy Apply): {title_label}", level="success", job_id=job_id)
            return "applied"

        # Otherwise click Next / Avançar / Review / Revisar
        next_btn = await _find_first(modal, next_selectors)
        if next_btn is not None:
            btn_label = (await next_btn.inner_text()).strip() or "Next"
            await next_btn.click()
            await browser_manager.log(f"➡️ Easy Apply Step {step}: clicked '{btn_label}'.", job_id=job_id)
            await asyncio.sleep(1.8)
            # Check if validation errors appeared
            err_count = await modal.locator(".artdeco-inline-feedback--error:visible").count()
            if err_count > 0:
                decision = await browser_manager.request_human_action(
                    reason=f"LinkedIn Easy Apply (Step {step}) showed a validation error. Please fix the highlighted field in the browser and click Resume.",
                    url=page.url,
                    job_id=job_id,
                    job_title=title_label,
                )
                if decision == "skip":
                    await db.update_job(job_id, status="skipped", status_note="Skipped at validation error.")
                    return "skipped"
                if decision == "abort":
                    return "abort"
        else:
            decision = await browser_manager.request_human_action(
                reason=f"Easy Apply paused on Step {step} (no Next/Submit button detected). Complete this step in the browser and click Resume.",
                url=page.url,
                job_id=job_id,
                job_title=title_label,
            )
            if decision == "skip":
                await db.update_job(job_id, status="skipped", status_note="Skipped during Easy Apply.")
                return "skipped"
            if decision == "abort":
                return "abort"

    await db.update_job(job_id, status="needs_action", status_note="Easy Apply reached max steps; check browser.")
    return "needs_action"

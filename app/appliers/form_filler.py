"""Shared Playwright DOM form inspector, CV uploader, and Gemini-powered field filler."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from app import database as db
from app.ai_engine import ai_engine
from app.browser_manager import browser_manager


def format_phone_for_job(raw_phone: str, job: dict[str, Any]) -> str:
    """For Brazilian jobs, strip the +55 country code since national format is expected."""
    phone = (raw_phone or "").strip()
    if not phone:
        return ""
    loc_low = (job.get("location") or "").lower()
    is_br = (not job.get("is_international")) or any(
        k in loc_low for k in ("brazil", "brasil", "são paulo", "sao paulo", "- sp", ", sp")
    )
    if is_br:
        # Strip leading +55 or 0055 (and optional whitespace/dash)
        cleaned = re.sub(r"^\s*(?:\+55|0055)[\s\-]*", "", phone)
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) in (12, 13) and digits.startswith("55"):
            cleaned = digits[2:]
        return cleaned.strip()
    return phone


async def detect_login_or_roadblock(page) -> str | None:
    """Detect common login walls, account creation prompts, or human verification checks."""
    url_low = page.url.lower()
    if any(k in url_low for k in ("/login", "/signin", "/sign-in", "/auth", "/register", "/signup", "login.gupy.io")):
        return "This site requires you to sign in or create an account. Use the browser window (or click 'Auto-fill Saved Login'), then click Resume."

    # Check for visible password input + login/register context
    pwd_count = await page.locator("input[type='password']:visible").count()
    if pwd_count > 0:
        return "A login or account-creation form was detected. Please sign in or create your account in the browser window, then click Resume."

    # Check for CAPTCHA / human verification iframes (never bypass; always let user solve)
    captcha_selectors = (
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "iframe[src*='turnstile']",
        "iframe[title*='captcha' i]",
    )
    for sel in captcha_selectors:
        if await page.locator(sel).count() > 0:
            return "A human verification (CAPTCHA) check is shown. Please complete it in the browser window, then click Resume."

    return None


async def upload_matching_resume(page, job: dict[str, Any], container=None) -> bool:
    """Upload the candidate's resume matching the job's language (pt/en/it) into any visible file input."""
    resume = await db.get_resume_for_language(job.get("language", "pt"))
    if not resume:
        return False
    resume_path = Path(resume["stored_path"])
    if not resume_path.exists():
        return False

    scope = container if container is not None else page
    file_inputs = scope.locator("input[type='file']")
    count = await file_inputs.count()
    for i in range(count):
        inp = file_inputs.nth(i)
        try:
            accept = (await inp.get_attribute("accept") or "").lower()
            if "image" in accept and "pdf" not in accept and "doc" not in accept:
                continue
            await inp.set_input_files(str(resume_path))
            await browser_manager.log(
                f"📎 Uploaded resume '{resume['filename']}' ({resume['language'].upper()})",
                job_id=job.get("id"),
            )
            return True
        except Exception:
            continue

    # Fallback for React/Vue dropzones that trigger a file chooser on button click (e.g., Quickin 'ESCOLHER ARQUIVO')
    upload_btn_texts = (
        "escolher arquivo",
        "selecionar arquivo",
        "enviar currículo",
        "enviar curriculo",
        "anexar currículo",
        "upload resume",
        "choose file",
        "attach resume",
        "carica cv",
    )
    for txt in upload_btn_texts:
        btn = scope.locator(f"button:has-text('{txt}'), label:has-text('{txt}'), [role='button']:has-text('{txt}')").first
        if await btn.count() > 0:
            try:
                if not await btn.is_visible():
                    continue
                async with page.expect_file_chooser(timeout=4000) as fc_info:
                    await btn.click(timeout=3000)
                fc = await fc_info.value
                await fc.set_files(str(resume_path))
                await browser_manager.log(
                    f"📎 Uploaded resume via file chooser: '{resume['filename']}' ({resume['language'].upper()})",
                    job_id=job.get("id"),
                )
                return True
            except Exception:
                continue
    return False


async def fill_visible_form_fields(page, job: dict[str, Any], container=None) -> tuple[int, list[str]]:
    """
    Inspect visible empty form fields inside `container` (or whole `page`),
    ask the Form-Filler Agent to answer them in the job's language, and fill them in.
    Returns (filled_count, list_of_field_labels_needing_human_input).
    """
    scope = container if container is not None else page

    # Extract form fields via JS inside the container or document
    js_extract = """
    (root) => {
      const container = root || document;
      const fields = [];
      const seen = new Set();

      function getLabel(el) {
        if (el.id) {
          const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
        }
        const parentLabel = el.closest('label');
        if (parentLabel && parentLabel.innerText.trim()) return parentLabel.innerText.trim();
        const group = el.closest('fieldset, .fb-dash-form-element, .form-group, .field, .v-input, .el-form-item');
        if (group) {
          const legend = group.querySelector('legend, label, .fb-dash-form-element__label, span[aria-hidden="true"]');
          if (legend && legend.innerText.trim()) return legend.innerText.trim();
        }
        // Climb up 2 parent divs for React/Vue layouts (e.g. Quickin) where <label> is a sibling above the input wrapper
        let p = el.parentElement;
        for (let depth = 0; depth < 3 && p; depth++) {
          const lbl = p.querySelector(':scope > label, :scope > div > label');
          if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
          p = p.parentElement;
        }
        const aria = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '';
        return aria.trim();
      }

      const elements = container.querySelectorAll('input, textarea, select');
      let idx = 0;
      for (const el of elements) {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || el.disabled) continue;
        const type = (el.type || el.tagName).toLowerCase();
        if (['hidden', 'submit', 'button', 'file', 'password', 'image', 'reset', 'search'].includes(type)) continue;

        const key = el.name || el.id || `auto_field_${idx}`;
        if (type === 'radio') {
          if (seen.has(key)) continue;
          seen.add(key);
          const radios = Array.from(container.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`));
          const alreadyChecked = radios.some(r => r.checked);
          if (alreadyChecked) continue;
          const options = radios.map(r => getLabel(r) || r.value).filter(Boolean);
          const group = el.closest('fieldset, .fb-dash-form-element');
          const label = group ? (group.querySelector('legend, span')?.innerText?.trim() || el.name) : el.name;
          el.setAttribute('data-jh-id', `jh_${idx}`);
          fields.push({ id: `jh_${idx}`, radio_name: el.name, label, type: 'radio', options, required: el.required || true });
          idx++;
          continue;
        }

        if (el.tagName === 'SELECT') {
          const currentVal = el.value;
          const options = Array.from(el.options).map(o => o.text.trim()).filter(t => t && !/^(select|selecione|escolha|seleziona|--)/i.test(t));
          if (currentVal && !/^(select|selecione|escolha|seleziona|--|)$/i.test(el.options[el.selectedIndex]?.text?.trim() || '')) continue;
          el.setAttribute('data-jh-id', `jh_${idx}`);
          fields.push({ id: `jh_${idx}`, label: getLabel(el), type: 'select', options, required: el.required });
          idx++;
          continue;
        }

        if (type === 'checkbox') {
          if (el.checked) continue;
          el.setAttribute('data-jh-id', `jh_${idx}`);
          fields.push({ id: `jh_${idx}`, label: getLabel(el), type: 'checkbox', options: [], required: el.required });
          idx++;
          continue;
        }

        // Text / email / tel / number / textarea
        if (el.value && el.value.trim().length > 0) continue;
        el.setAttribute('data-jh-id', `jh_${idx}`);
        fields.push({
          id: `jh_${idx}`,
          label: getLabel(el),
          type: el.tagName === 'TEXTAREA' ? 'textarea' : (type === 'number' ? 'number' : 'text'),
          options: [],
          required: el.required || el.getAttribute('aria-required') === 'true',
        });
        idx++;
      }
      return fields;
    }
    """

    try:
        if container is not None:
            handle = await container.element_handle()
            extracted = await page.evaluate(js_extract, handle)
        else:
            extracted = await page.evaluate(js_extract, None)
    except Exception:
        return 0, []

    if not extracted:
        return 0, []

    # Pre-fill standard profile fields, referral source ("LinkedIn"), BR national phone,
    # and on-demand Cover Letter / T-Letter ONLY when the form actually asks for one.
    profile = await db.get_profile()
    formatted_phone = format_phone_for_job(profile.get("phone", ""), job)
    remaining_for_ai: list[dict[str, Any]] = []
    direct_answers: dict[str, Any] = {}

    heard_about_keywords = (
        "where did you hear",
        "how did you hear",
        "heard about",
        "referral source",
        "source of application",
        "onde soube",
        "como ficou sabendo",
        "como soube",
        "onde encontrou",
        "onde viu",
        "como nos conheceu",
        "come hai saputo",
        "come ci hai conosciuto",
    )
    cover_letter_keywords = (
        "cover letter",
        "carta de apresentação",
        "carta de apresentacao",
        "lettera di presentazione",
        "motivation letter",
        "apresente-se",
        "why do you want",
    )

    for f in extracted:
        lbl = (f.get("label") or "").lower()
        ftype = f.get("type")
        opts = f.get("options") or []

        # Rule: Always signal "LinkedIn" when asked where candidate heard about the position
        if any(k in lbl for k in heard_about_keywords):
            if ftype in ("select", "radio") and opts:
                li_opt = next((o for o in opts if "linkedin" in o.lower()), None)
                if li_opt:
                    direct_answers[f["id"]] = li_opt
                    continue
            elif ftype in ("text", "textarea"):
                direct_answers[f["id"]] = "LinkedIn"
                continue

        if ftype in ("text", "textarea"):
            if any(k in lbl for k in ("first name", "primeiro nome", "nome proprio")) and "last" not in lbl:
                direct_answers[f["id"]] = (profile.get("full_name") or "").split()[0] if profile.get("full_name") else ""
                continue
            if any(k in lbl for k in ("last name", "sobrenome", "cognome")):
                parts = (profile.get("full_name") or "").split()
                direct_answers[f["id"]] = " ".join(parts[1:]) if len(parts) > 1 else ""
                continue
            if any(k in lbl for k in ("full name", "nome completo", "nome e cognome")):
                direct_answers[f["id"]] = profile.get("full_name", "")
                continue
            if "email" in lbl or "e-mail" in lbl:
                direct_answers[f["id"]] = profile.get("email", "")
                continue
            if any(k in lbl for k in ("phone", "telefone", "celular", "whatsapp", "telefono")):
                direct_answers[f["id"]] = formatted_phone
                continue
            if "linkedin" in lbl:
                direct_answers[f["id"]] = profile.get("linkedin_url", "")
                continue
            if ftype == "textarea" and any(k in lbl for k in cover_letter_keywords):
                letter = job.get("generated_cover_letter") or job.get("generated_t_letter")
                if not letter:
                    try:
                        await browser_manager.log(
                            f"✍️ Application form requested a Cover Letter — Writer Agent generating one on demand ({(job.get('language') or 'pt').upper()})...",
                            job_id=job.get("id"),
                        )
                        mats = await ai_engine.generate_application_materials(job)
                        if job.get("id"):
                            await db.update_job(
                                job["id"],
                                generated_t_letter=mats["t_letter"],
                                generated_cover_letter=mats["cover_letter"],
                            )
                        job["generated_t_letter"] = mats["t_letter"]
                        job["generated_cover_letter"] = mats["cover_letter"]
                        letter = mats["cover_letter"] or mats["t_letter"]
                    except Exception as exc:
                        await browser_manager.log(f"On-demand letter generation failed: {exc}", level="warning", job_id=job.get("id"))
                if letter:
                    direct_answers[f["id"]] = letter
                    continue
        remaining_for_ai.append(f)

    needs_human_ids: set[str] = set()
    ai_answers: dict[str, Any] = {}
    if remaining_for_ai:
        ai_result = await ai_engine.answer_form_questions(job, remaining_for_ai)
        ai_answers = ai_result.get("answers", {})
        needs_human_ids = set(ai_result.get("needs_human", []))

    all_answers = {**direct_answers, **ai_answers}
    field_by_id = {f["id"]: f for f in extracted}

    filled_count = 0
    for fid, val in all_answers.items():
        if val is None or val == "":
            continue
        meta = field_by_id.get(fid)
        if not meta:
            continue
        ftype = meta["type"]
        try:
            if ftype == "radio":
                rname = meta.get("radio_name")
                radios = scope.locator(f"input[type='radio'][name='{rname}']")
                count = await radios.count()
                for i in range(count):
                    r = radios.nth(i)
                    r_val = (await r.get_attribute("value") or "").lower()
                    parent_text = (await r.locator("xpath=..").inner_text()).lower()
                    if str(val).lower() in (r_val, parent_text) or str(val).lower() in parent_text:
                        await r.check(force=True)
                        filled_count += 1
                        break
            elif ftype == "select":
                sel = scope.locator(f"[data-jh-id='{fid}']").first
                try:
                    await sel.select_option(label=str(val))
                except Exception:
                    await sel.select_option(value=str(val))
                filled_count += 1
            elif ftype == "checkbox":
                if val is True or str(val).lower() in ("true", "yes", "sim", "sì"):
                    await scope.locator(f"[data-jh-id='{fid}']").first.check(force=True)
                    filled_count += 1
            else:
                el = scope.locator(f"[data-jh-id='{fid}']").first
                await el.fill(str(val))
                filled_count += 1
        except Exception:
            if meta.get("required"):
                needs_human_ids.add(fid)

    return filled_count, [field_by_id[fid]["label"] or fid for fid in needs_human_ids if fid in field_by_id]

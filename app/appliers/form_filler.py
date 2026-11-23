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


def _parse_currency_numbers(text: str) -> list[float]:
    """Extract numeric currency values from PT/EN strings like 'Entre R$ 9.501,00 e R$ 11.000' or '$8k - $10k'."""
    if not text:
        return []
    nums: list[float] = []
    # Match formatted numbers with optional k/K suffix
    pattern = re.compile(r"(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?)(\s*[kK]\b)?")
    for m in pattern.finditer(text):
        raw = m.group(1)
        has_k = bool(m.group(2))
        try:
            if has_k:
                val = float(raw.replace(",", ".")) * 1000.0
            elif "." in raw and "," in raw:
                if raw.rfind(",") > raw.rfind("."):
                    # Brazilian/EU format: 1.501,00
                    val = float(raw.replace(".", "").replace(",", "."))
                else:
                    # US format: 1,501.00
                    val = float(raw.replace(",", ""))
            elif "." in raw:
                parts = raw.split(".")
                if len(parts[-1]) == 3 and all(len(p) == 3 for p in parts[1:]):
                    # Thousands separator: 2.500 or 11.000
                    val = float("".join(parts))
                else:
                    val = float(raw)
            elif "," in raw:
                parts = raw.split(",")
                if len(parts[-1]) == 3 and all(len(p) == 3 for p in parts[1:]):
                    # US thousands separator: 2,500
                    val = float("".join(parts))
                else:
                    # Decimal comma: 1500,00
                    val = float(raw.replace(",", "."))
            else:
                val = float(raw)
            nums.append(val)
        except ValueError:
            continue
    return nums


def compute_target_salary(profile: dict[str, Any]) -> float | None:
    """Compute the candidate's target average salary from salary_min / salary_max (or salary_expectation)."""
    try:
        smin = float(profile.get("salary_min") or 0)
    except (TypeError, ValueError):
        smin = 0.0
    try:
        smax = float(profile.get("salary_max") or 0)
    except (TypeError, ValueError):
        smax = 0.0

    if smin > 0 and smax > 0:
        return (smin + smax) / 2.0
    if smin > 0:
        return smin
    if smax > 0:
        return smax

    exp_text = str(profile.get("salary_expectation") or "")
    nums = [n for n in _parse_currency_numbers(exp_text) if n >= 500]
    if len(nums) >= 2:
        return (min(nums) + max(nums)) / 2.0
    if len(nums) == 1:
        return nums[0]
    return None


def _parse_salary_option_range(opt_text: str) -> tuple[float, float] | None:
    """Parse a salary range option into (low, high) bounds."""
    nums = _parse_currency_numbers(opt_text)
    if not nums:
        return None
    low_txt = opt_text.lower()
    if len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    val = nums[0]
    if any(k in low_txt for k in ("até", "ate ", "up to", "menos de", "below", "under", "fino a", "<")):
        return (0.0, val)
    if any(k in low_txt for k in ("acima", "mais de", "above", "over", "more than", "oltre", "+", ">")):
        return (val, float("inf"))
    return (val, val)


def looks_like_salary_options(options: list[str]) -> bool:
    """Detect whether a list of radio/select options represents salary brackets."""
    if len(options) < 2:
        return False
    currency_hits = 0
    for opt in options:
        low = opt.lower()
        has_currency = any(sym in opt for sym in ("R$", "$", "€", "£")) or any(
            k in low for k in ("brl", "usd", "eur", "reais", "mil")
        )
        nums = _parse_currency_numbers(opt)
        if has_currency and nums:
            currency_hits += 1
        elif len(nums) >= 2 and max(nums) >= 1000:
            currency_hits += 1
    return currency_hits >= 2


def select_salary_option(
    options: list[str],
    profile: dict[str, Any],
    question_label: str = "",
) -> str | None:
    """Choose the option whose salary bracket contains (or is closest to) the candidate's average salary."""
    target = compute_target_salary(profile)
    if target is None or target <= 0 or not options:
        return None

    parsed: list[tuple[str, float, float]] = []
    for opt in options:
        rng = _parse_salary_option_range(opt)
        if rng is not None:
            parsed.append((opt, rng[0], rng[1]))
    if not parsed:
        return None

    # Auto-adjust monthly vs annual if the scale clearly differs (e.g. profile monthly 10k vs annual 120k options)
    finite_vals = [v for _, lo, hi in parsed for v in (lo, hi) if v > 0 and v != float("inf")]
    period = (profile.get("salary_period") or "monthly").lower()
    q_low = (question_label or "").lower()
    if finite_vals:
        median_opt = sorted(finite_vals)[len(finite_vals) // 2]
        if period == "monthly" and (any(k in q_low for k in ("annual", "anual", "per year", "ao ano")) or (target < 35000 and median_opt > 50000)):
            target *= 12.0
        elif period == "annual" and (any(k in q_low for k in ("mensal", "monthly", "por mês", "por mes", "clt")) or (target > 50000 and median_opt < 35000)):
            target /= 12.0

    # 1. Prefer exact bracket match (low <= target <= high)
    for opt, lo, hi in parsed:
        if lo <= target <= hi:
            return opt

    # 2. Otherwise pick the closest bracket
    def _dist(lo: float, hi: float) -> float:
        if target < lo:
            return lo - target
        if target > hi:
            return target - hi
        return 0.0

    best_opt = min(parsed, key=lambda item: _dist(item[1], item[2]))[0]
    return best_opt


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

      function getRadioOptionLabel(el) {
        if (el.id) {
          const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
        }
        const parentLabel = el.closest('label');
        if (parentLabel && parentLabel.innerText.trim()) return parentLabel.innerText.trim();
        if (el.parentElement && el.parentElement.innerText && el.parentElement.innerText.trim().length < 140) {
          return el.parentElement.innerText.trim();
        }
        return (el.getAttribute('aria-label') || el.value || '').trim();
      }

      function getRadioGroupLabel(radios, fallback) {
        const first = radios[0];
        const optionSet = new Set(radios.map(r => getRadioOptionLabel(r).toLowerCase()));
        let node = first.closest('fieldset, [role="radiogroup"], .fb-dash-form-element, .form-group') || first.parentElement;
        for (let depth = 0; depth < 5 && node && node !== document.body; depth++) {
          const candidates = node.querySelectorAll('legend, h1, h2, h3, h4, p, [class*="question" i], [class*="title" i], [class*="label" i]');
          for (const c of candidates) {
            if (c.querySelector('input[type="radio"]')) continue;
            const txt = (c.innerText || '').trim();
            if (txt && txt.length >= 4 && txt.length <= 260 && !optionSet.has(txt.toLowerCase())) {
              return txt;
            }
          }
          // Check previous sibling heading/paragraph
          let prev = node.previousElementSibling;
          if (prev) {
            const txt = (prev.innerText || '').trim();
            if (txt && txt.length >= 4 && txt.length <= 260 && !optionSet.has(txt.toLowerCase())) {
              return txt;
            }
          }
          node = node.parentElement;
        }
        return fallback;
      }

      const elements = container.querySelectorAll('input, textarea, select');
      let idx = 0;
      for (const el of elements) {
        const type = (el.type || el.tagName).toLowerCase();
        if (el.disabled) continue;
        if (['hidden', 'submit', 'button', 'file', 'password', 'image', 'reset', 'search'].includes(type)) continue;

        const style = window.getComputedStyle(el);
        const isVis = style.display !== 'none' && style.visibility !== 'hidden';
        if (!isVis && type !== 'radio') continue;

        const key = el.name || el.id || `auto_field_${idx}`;
        if (type === 'radio') {
          if (seen.has(key)) continue;
          const radios = el.name
            ? Array.from(container.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`))
            : [el];
          // Ensure at least one radio or its parent label is actually visible on screen
          const anyVisible = radios.some(r => {
            const s = window.getComputedStyle(r);
            if (s.display !== 'none' && s.visibility !== 'hidden') return true;
            const lbl = (r.id && document.querySelector(`label[for="${CSS.escape(r.id)}"]`)) || r.closest('label') || r.parentElement;
            if (!lbl) return false;
            const ls = window.getComputedStyle(lbl);
            return ls.display !== 'none' && ls.visibility !== 'hidden' && lbl.getBoundingClientRect().height > 0;
          });
          if (!anyVisible) continue;
          seen.add(key);
          const alreadyChecked = radios.some(r => r.checked);
          if (alreadyChecked) continue;
          const fid = `jh_${idx}`;
          const options = [];
          radios.forEach((r, rIdx) => {
            r.setAttribute('data-jh-radio-group', fid);
            r.setAttribute('data-jh-radio-opt', String(rIdx));
            options.push(getRadioOptionLabel(r) || r.value || `Option ${rIdx + 1}`);
          });
          const label = getRadioGroupLabel(radios, el.name || '');
          el.setAttribute('data-jh-id', fid);
          fields.push({ id: fid, radio_name: el.name, label, type: 'radio', options, required: el.required || true });
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

      // Also support custom ARIA radiogroups (e.g. React/MUI/Gupy without native <input type="radio">)
      const ariaGroups = container.querySelectorAll('[role="radiogroup"]');
      for (const grp of ariaGroups) {
        if (grp.querySelector('input[type="radio"]')) continue; // already handled above
        const items = Array.from(grp.querySelectorAll('[role="radio"]'));
        if (!items.length) continue;
        if (items.some(it => it.getAttribute('aria-checked') === 'true')) continue;
        const fid = `jh_${idx}`;
        const options = [];
        items.forEach((it, rIdx) => {
          it.setAttribute('data-jh-radio-group', fid);
          it.setAttribute('data-jh-radio-opt', String(rIdx));
          options.push((it.innerText || it.getAttribute('aria-label') || '').trim() || `Option ${rIdx + 1}`);
        });
        const label = grp.getAttribute('aria-label') || getRadioGroupLabel(items, '');
        fields.push({ id: fid, radio_name: '', label, type: 'radio', options, is_aria_radio: true, required: true });
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
    salary_keywords = (
        "pretensão",
        "pretensao",
        "remuneração",
        "remuneracao",
        "salário",
        "salario",
        "faixa salarial",
        "salary",
        "compensation",
        "pay expectation",
        "expected pay",
        "retribuzione",
        "ral",
    )
    target_salary = compute_target_salary(profile)

    for f in extracted:
        lbl = (f.get("label") or "").lower()
        ftype = f.get("type")
        opts = f.get("options") or []

        # Rule: Match salary range options (radio/select) or text/number inputs to the candidate's average salary
        is_salary_q = any(k in lbl for k in salary_keywords) or (ftype in ("radio", "select") and looks_like_salary_options(opts))
        if is_salary_q and target_salary is not None:
            if ftype in ("radio", "select") and opts:
                best_salary_opt = select_salary_option(opts, profile, f.get("label") or "")
                if best_salary_opt:
                    direct_answers[f["id"]] = best_salary_opt
                    await browser_manager.log(
                        f"💰 Matched average salary ({target_salary:,.0f}) → selected '{best_salary_opt}'",
                        job_id=job.get("id"),
                    )
                    continue
            elif ftype in ("text", "number"):
                direct_answers[f["id"]] = str(int(round(target_salary)))
                await browser_manager.log(
                    f"💰 Filled average salary expectation: {int(round(target_salary))}",
                    job_id=job.get("id"),
                )
                continue

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
                            f"✍️ Application form demanded a Cover Letter — Writer Agent drafting first-person letter (≤850 chars, {(job.get('language') or 'pt').upper()})...",
                            job_id=job.get("id"),
                        )
                        c_text = await ai_engine.generate_single_letter(job, letter_type="cover_letter", regenerate=False)
                        if job.get("id"):
                            await db.update_job(job["id"], generated_cover_letter=c_text)
                        job["generated_cover_letter"] = c_text
                        letter = c_text
                    except Exception as exc:
                        await browser_manager.log(f"On-demand letter generation failed: {exc}", level="warning", job_id=job.get("id"))
                if letter:
                    direct_answers[f["id"]] = letter
                    # Mark that a letter was inserted so the applier ALWAYS pauses for user approval before submit
                    job["_letter_requires_approval"] = True
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
                opts_list = meta.get("options") or []
                val_low = str(val).strip().lower()
                matched_idx = None
                for o_idx, o_txt in enumerate(opts_list):
                    if o_txt.strip().lower() == val_low or val_low in o_txt.strip().lower():
                        matched_idx = o_idx
                        break

                clicked = False
                if matched_idx is not None:
                    target_radio = scope.locator(
                        f"[data-jh-radio-group='{fid}'][data-jh-radio-opt='{matched_idx}']"
                    ).first
                    if await target_radio.count() > 0:
                        try:
                            await target_radio.scroll_into_view_if_needed(timeout=3000)
                        except Exception:
                            pass
                        if meta.get("is_aria_radio"):
                            await target_radio.click(force=True)
                            clicked = True
                        else:
                            # Prefer clicking associated <label> (triggers React onChange cleanly), fallback to .check(force=True)
                            rid = await target_radio.get_attribute("id")
                            if rid:
                                lbl_el = page.locator(f"label[for='{rid}']").first
                                if await lbl_el.count() > 0 and await lbl_el.is_visible():
                                    try:
                                        await lbl_el.click(timeout=3000)
                                        clicked = True
                                    except Exception:
                                        pass
                            if not clicked:
                                try:
                                    await target_radio.check(force=True, timeout=3000)
                                    clicked = True
                                except Exception:
                                    await target_radio.evaluate("n => n.click()")
                                    clicked = True

                if not clicked:
                    rname = meta.get("radio_name")
                    if rname:
                        radios = scope.locator(f"input[type='radio'][name='{rname}']")
                        count = await radios.count()
                        for i in range(count):
                            r = radios.nth(i)
                            r_val = (await r.get_attribute("value") or "").lower()
                            parent_text = (await r.locator("xpath=..").inner_text()).lower()
                            if val_low in (r_val, parent_text) or val_low in parent_text:
                                await r.check(force=True)
                                clicked = True
                                break
                if clicked:
                    filled_count += 1
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

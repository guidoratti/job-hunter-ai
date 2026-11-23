"""Google Gemini AI engine for job matching, language detection, T-Letters, and form filling."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app import database as db

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_AGENT_MODEL = f"gemini:{DEFAULT_GEMINI_MODEL}"

FALLBACK_MODELS = [
    "gemini:gemini-3.8-flash",
    "gemini:gemini-3.5-flash",
    "gemini:gemini-3.5-flash-lite",
    "gemini:gemini-3.1-flash-lite",
]

DEPRECATED_MODEL_MAP = {
    "gemini-2.5-flash": "gemini-3.8-flash",
    "gemini-2.5-pro": "gemini-3.5-flash",
    "gemini-3.8-pro": "gemini-3.8-flash",
    "gemini-2.0-flash": "gemini-3.8-flash",
    "gemini:gemini-2.5-flash": "gemini:gemini-3.8-flash",
    "gemini:gemini-2.5-pro": "gemini:gemini-3.5-flash",
    "gemini:gemini-3.8-pro": "gemini:gemini-3.8-flash",
    "gemini:gemini-2.0-flash": "gemini:gemini-3.8-flash",
}

PROVIDER_KEY_SETTINGS = {
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "openrouter": "openrouter_api_key",
}


def normalize_model_spec(spec: str) -> str:
    raw = (spec or "").strip()
    if not raw:
        return DEFAULT_AGENT_MODEL
    if raw in DEPRECATED_MODEL_MAP:
        raw = DEPRECATED_MODEL_MAP[raw]
    if ":" not in raw:
        return f"gemini:{raw}"
    return raw


def parse_model_spec(spec: str) -> tuple[str, str]:
    norm = normalize_model_spec(spec)
    provider, model_id = norm.split(":", 1)
    return provider.strip().lower(), model_id.strip()

SP_METRO_KEYWORDS = (
    "cotia",
    "são paulo",
    "sao paulo",
    "barueri",
    "alphaville",
    "osasco",
    "taboão",
    "taboao",
    "itapevi",
    "carapicuíba",
    "carapicuiba",
    "grande são paulo",
    "sp, brazil",
    "sp, brasil",
    "- sp",
)

BRAZIL_KEYWORDS = ("brazil", "brasil", ", sp", ", rj", ", mg", ", pr", ", rs", ", sc", ", df", "latam")


def compute_priority_tier(location: str, work_mode: str, is_international: bool) -> int:
    """
    Priority order per user preference:
    1 = Cotia / São Paulo metro + Hybrid
    2 = Cotia / São Paulo / Brazil + Remote
    3 = International + Remote
    4 = Cotia / São Paulo + On-site / Unknown
    5 = International + Non-Remote (or other non-SP on-site)
    """
    loc = (location or "").lower()
    mode = (work_mode or "unknown").lower()
    in_sp_metro = any(k in loc for k in SP_METRO_KEYWORDS)

    if is_international:
        return 3 if mode == "remote" else 5

    if in_sp_metro and mode == "hybrid":
        return 1
    if mode == "remote":
        return 2
    if in_sp_metro and mode in ("onsite", "unknown"):
        return 4
    if mode == "hybrid":
        return 4
    return 5


def detect_language_heuristic(text: str) -> str:
    sample = (text or "").lower()
    pt_hits = sum(
        1
        for w in (
            "vaga",
            "requisitos",
            "experiência",
            "benefícios",
            "trabalho",
            "atuar",
            "gestão",
            "empresa",
            "conhecimento",
            "híbrido",
            "remoto",
            "presencial",
        )
        if w in sample
    )
    it_hits = sum(
        1
        for w in (
            "requisiti",
            "esperienza",
            "lavoro",
            "azienda",
            "gestione",
            "competenze",
            "ruolo",
            "sede",
            "ibrido",
            "remoto",
            "candidatura",
        )
        if w in sample
    )
    en_hits = sum(
        1
        for w in (
            "requirements",
            "experience",
            "responsibilities",
            "qualifications",
            "benefits",
            "hybrid",
            "remote",
            "management",
            "company",
            "apply",
        )
        if w in sample
    )
    if it_hits > pt_hits and it_hits > en_hits and it_hits >= 2:
        return "it"
    if pt_hits >= en_hits and pt_hits >= 2:
        return "pt"
    if en_hits >= 2:
        return "en"
    return "pt"


def infer_work_mode_heuristic(text: str, location: str) -> tuple[str, bool]:
    combined = f"{location} {text}".lower()
    if any(k in combined for k in ("híbrido", "hibrido", "hybrid", "ibrido")):
        mode = "hybrid"
    elif any(k in combined for k in ("remoto", "remote", "home office", "trabalho remoto", "da remoto")):
        mode = "remote"
    elif any(k in combined for k in ("presencial", "on-site", "onsite", "in loco", "in sede")):
        mode = "onsite"
    else:
        mode = "unknown"

    loc_low = (location or "").lower()
    is_brazil = any(k in loc_low for k in SP_METRO_KEYWORDS) or any(k in loc_low for k in BRAZIL_KEYWORDS)
    is_intl = bool(loc_low.strip()) and not is_brazil and "worldwide" not in loc_low and "global" not in loc_low
    if any(k in loc_low for k in ("worldwide", "global", "emea", "united states", "usa", "uk", "europe", "italy", "italia", "canada", "germany", "spain", "portugal")):
        is_intl = True
    return mode, is_intl


FX_TO_BRL = {"BRL": 1.0, "USD": 5.8, "EUR": 6.2}


def _to_monthly_brl(amount: float, currency: str, period: str) -> float:
    if not amount or amount <= 0:
        return 0.0
    rate = FX_TO_BRL.get((currency or "BRL").upper(), 1.0)
    brl = amount * rate
    return brl / 12.0 if (period or "monthly").lower() == "yearly" else brl


def evaluate_salary_fit(
    est_min: int,
    est_avg: int,
    est_max: int,
    est_currency: str,
    est_period: str,
    profile: dict[str, Any],
) -> str:
    """Compare estimated job salary against user's configured min/max range (normalized to monthly BRL)."""
    user_min = int(profile.get("salary_min") or 0)
    user_max = int(profile.get("salary_max") or 0)
    if (user_min <= 0 and user_max <= 0) or (est_avg <= 0 and est_max <= 0):
        return "unknown"

    u_cur = profile.get("salary_currency") or "BRL"
    u_per = profile.get("salary_period") or "monthly"
    u_min_norm = _to_monthly_brl(user_min, u_cur, u_per)
    u_max_norm = _to_monthly_brl(user_max, u_cur, u_per)

    ref_val = est_avg if est_avg > 0 else ((est_min + est_max) / 2.0)
    est_norm = _to_monthly_brl(ref_val, est_currency, est_period)
    est_max_norm = _to_monthly_brl(est_max or ref_val, est_currency, est_period)

    if u_min_norm > 0 and est_max_norm < u_min_norm * 0.95:
        return "below_range"
    if u_max_norm > 0 and est_norm > u_max_norm * 1.05:
        return "above_range"
    if u_min_norm > 0 and est_norm < u_min_norm:
        # Average is slightly below min, but max reaches into range -> still borderline in_range
        return "in_range" if est_max_norm >= u_min_norm else "below_range"
    return "in_range"


def _extract_json_block(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    return json.loads(raw)


class AIEngine:
    async def _get_provider_keys(self) -> dict[str, str]:
        keys: dict[str, str] = {}
        for prov, setting_key in PROVIDER_KEY_SETTINGS.items():
            val = await db.get_setting(setting_key)
            if val:
                keys[prov] = val.strip()
        ollama_url = (await db.get_setting("ollama_url") or "").strip()
        if ollama_url:
            keys["ollama"] = ollama_url.rstrip("/")
        return keys

    async def has_any_provider(self) -> bool:
        return bool(await self._get_provider_keys())

    async def _get_role_candidates(self, role: str) -> list[str]:
        """Build ordered list of provider:model specs for a specialized agent role with cross-vendor failover."""
        role_key_map = {
            "matcher": "agent_matcher_model",
            "writer": "agent_writer_model",
            "form": "agent_form_model",
        }
        legacy_model = await db.get_setting("gemini_model") or DEFAULT_GEMINI_MODEL
        primary = await db.get_setting(role_key_map.get(role, "")) or normalize_model_spec(legacy_model)
        fallback = await db.get_setting("agent_fallback_model") or ""

        ordered: list[str] = []
        for item in [primary, fallback, *FALLBACK_MODELS]:
            if not item:
                continue
            norm = normalize_model_spec(item)
            if norm not in ordered:
                ordered.append(norm)
        return ordered

    def _call_provider(self, provider: str, model_id: str, api_key: str, prompt: str) -> str:
        """Invoke a single LLM vendor synchronously and return plain text."""
        if provider == "gemini":
            from google import genai

            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(model=model_id, contents=prompt)
            return resp.text or ""

        if provider == "openai":
            resp = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                },
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""

        if provider == "openrouter":
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://127.0.0.1:8000",
                    "X-Title": "Job Hunter AI",
                },
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                },
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""

        if provider == "anthropic":
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_id,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()
            blocks = data.get("content", [])
            return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")

        if provider == "ollama":
            base_url = (api_key or "http://127.0.0.1:11434").rstrip("/")
            payload: dict[str, Any] = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
            if "Return ONLY a valid JSON object" in prompt:
                payload["format"] = "json"
            resp = httpx.post(
                f"{base_url}/api/chat",
                json=payload,
                timeout=180.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return (data.get("message") or {}).get("content") or ""

        raise ValueError(f"Unsupported AI provider: {provider}")

    async def _generate_for_role(self, role: str, prompt: str) -> str:
        """Route prompt to the specialized agent's model with automatic cross-vendor failover."""
        keys = await self._get_provider_keys()
        if not keys:
            raise RuntimeError("No AI provider API key is configured. Add at least one key in Settings.")

        candidates = await self._get_role_candidates(role)
        # Filter to providers that actually have an API key saved
        usable = [spec for spec in candidates if parse_model_spec(spec)[0] in keys]
        # If none of the configured role models had keys, add a default for whichever provider key exists
        if not usable:
            default_by_prov = {
                "gemini": "gemini:gemini-3.8-flash",
                "openai": "openai:gpt-4.1-mini",
                "anthropic": "anthropic:claude-sonnet-4-20250514",
                "openrouter": "openrouter:google/gemma-3-27b-it:free",
                "ollama": "ollama:gemma3:12b",
            }
            for prov in keys:
                if prov in default_by_prov:
                    usable.append(default_by_prov[prov])

        last_err: Exception | None = None
        for spec in usable:
            prov, model_id = parse_model_spec(spec)
            api_key = keys.get(prov)
            if not api_key:
                continue
            try:
                return self._call_provider(prov, model_id, api_key, prompt)
            except Exception as exc:
                last_err = exc
                continue
        raise last_err or RuntimeError("All configured AI models failed.")

    async def test_provider(self, provider: str, model_spec: str = "") -> dict[str, str]:
        """Quick live ping for a single provider from the Settings UI."""
        prov = (provider or "").strip().lower()
        keys = await self._get_provider_keys()
        if prov == "ollama":
            base_url = (keys.get("ollama") or "http://127.0.0.1:11434").rstrip("/")
            resp = httpx.get(f"{base_url}/api/tags", timeout=8.0)
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            summary = ", ".join(models[:5]) if models else "Running (no models pulled yet — run: ollama pull gemma3:12b)"
            return {"provider": "ollama", "model": base_url, "reply": summary}

        api_key = keys.get(prov)
        if not api_key:
            raise RuntimeError(f"No API key saved for {prov}.")
        default_ping = {
            "gemini": "gemini-3.5-flash",
            "openai": "gpt-4.1-mini",
            "anthropic": "claude-3-5-haiku-latest",
            "openrouter": "google/gemma-3-27b-it:free",
        }
        model_id = parse_model_spec(model_spec)[1] if model_spec else default_ping.get(prov, "")
        reply = self._call_provider(prov, model_id, api_key, "Reply with just OK")
        return {"provider": prov, "model": model_id, "reply": reply.strip()[:80]}

    async def build_candidate_context(self, target_lang: str | None = None, compact: bool = False) -> str:
        profile = await db.get_profile()
        docs = [] if compact else await db.list_documents(include_text=True)
        mp = profile.get("match_preferences") or {}
        pref_lang = (profile.get("preferred_language") or "pt").lower()
        active_lang = (target_lang or pref_lang).lower()

        # Deduplicate documents by filename and prioritize files matching active_lang (then pref_lang)
        seen_files: set[str] = set()
        unique_docs: list[dict[str, Any]] = []
        for d in docs:
            key = f"{d['language']}:{d['filename']}"
            if key not in seen_files:
                seen_files.add(key)
                unique_docs.append(d)

        unique_docs.sort(
            key=lambda d: (
                0 if (d.get("priority") or "primary").lower() == "primary" else 1,
                0 if (d.get("language") or "").lower() == active_lang else (1 if (d.get("language") or "").lower() == pref_lang else 2),
                0 if d.get("doc_type") == "resume" else 1,
            )
        )

        loc_map = profile.get("localized") or {}
        lang_bucket = loc_map.get(active_lang) or loc_map.get(pref_lang) or {}
        eff_summary = (lang_bucket.get("summary") or "").strip() or profile.get("summary", "")
        eff_history = (lang_bucket.get("work_history") or "").strip() or profile.get("work_history", "")
        eff_t_letters = (lang_bucket.get("t_letter_examples") or "").strip() or profile.get("t_letter_examples", "")

        parts = [
            f"Candidate Name: {profile.get('full_name')}",
            f"Contact: {profile.get('email')} | {profile.get('phone')} | {profile.get('linkedin_url')}",
            f"Location: {profile.get('city')}, {profile.get('state')}, {profile.get('country')}",
            f"Primary / Preferential Language: {pref_lang.upper()} (Active Reference Language: {active_lang.upper()})",
            f"Target Roles: {', '.join(profile.get('target_roles', []))}",
            f"Languages: {json.dumps(profile.get('languages', []), ensure_ascii=False)}",
            f"Summary:\n{eff_summary}",
            f"Work History & Achievements:\n{eff_history}",
            f"T-Letter Style Guide:\n{eff_t_letters}",
        ]
        if mp:
            parts.append(
                "Personal Positioning, Culture & Matching Preferences:\n"
                f"- Core Skills & Domains: {mp.get('skills', '')}\n"
                f"- Preferred Industries / Sectors: {mp.get('industries', '')}\n"
                f"- Target Seniority: {mp.get('seniority', 'Any')}\n"
                f"- Culture, Values & Work Style: {mp.get('culture_values', '')}\n"
                f"- Personal Positioning / What I'm Looking For: {mp.get('personal_positioning', '')}\n"
                f"- Dealbreakers / Avoid: {mp.get('dealbreakers', '')}"
            )
        for doc in unique_docs:
            text = (doc.get("extracted_text") or "").strip()
            if text:
                priority_tag = "PRIMARY REFERENCE" if (doc.get("priority") or "primary").lower() == "primary" else "SECONDARY REFERENCE"
                parts.append(
                    f"--- [{priority_tag}] Uploaded Document ({doc['doc_type']} / {doc['language'].upper()}): {doc['filename']} ---\n{text[:12000]}"
                )
        return "\n\n".join(parts)

    async def analyze_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Score compatibility, detect language, work mode, international status, and priority tier."""
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "")
        description = job.get("description", "")

        fallback_lang = detect_language_heuristic(f"{title}\n{description}")
        fallback_mode, fallback_intl = infer_work_mode_heuristic(description, location)

        if not await self.has_any_provider():
            # Heuristic scoring fallback when no AI API key is configured yet
            profile = await db.get_profile()
            target_tokens = set(
                re.findall(r"[a-zà-ú]{3,}", " ".join(profile.get("target_roles", [])).lower())
            )
            title_tokens = set(re.findall(r"[a-zà-ú]{3,}", title.lower()))
            overlap = len(target_tokens & title_tokens)
            score = min(92, 45 + overlap * 15) if overlap else 35
            tier = compute_priority_tier(location, fallback_mode, fallback_intl)
            if tier == 5:
                score = min(score, 25)
            return {
                "language": fallback_lang,
                "work_mode": fallback_mode,
                "is_international": fallback_intl,
                "match_score": score,
                "priority_tier": tier,
                "match_reason": "Heuristic match (add your Gemini API key in Settings for deep semantic AI matching).",
                "missing_skills": "",
            }

        profile = await db.get_profile()
        context = await self.build_candidate_context(target_lang=fallback_lang, compact=True)
        mp = profile.get("match_preferences") or {}
        pref_lang = (profile.get("preferred_language") or "pt").lower()
        cand_name = profile.get("full_name") or "the candidate"
        cand_loc = ", ".join(p for p in (profile.get("city"), profile.get("state"), profile.get("country")) if p) or "their home city"
        u_min = profile.get("salary_min") or 0
        u_max = profile.get("salary_max") or 0
        u_cur = profile.get("salary_currency") or "BRL"
        u_per = profile.get("salary_period") or "monthly"

        prompt = f"""You are an executive career advisor evaluating a job posting for {cand_name} with BOTH technical rigor AND a human/cultural fit lens.

CANDIDATE PROFILE:
{context}

HUMAN FIT, SKILLS & CULTURE PREFERENCES:
- Highlighted Skills & Domains: {mp.get('skills', '')}
- Preferred Industries: {mp.get('industries', '')}
- Target Seniority: {mp.get('seniority', 'Any')}
- Culture & Work Style: {mp.get('culture_values', '')}
- Personal Positioning / Career Intent: {mp.get('personal_positioning', '')}
- Dealbreakers / Exclude: {mp.get('dealbreakers', '')}

CANDIDATE SALARY RANGE PREFERENCE:
Min: {u_min} {u_cur}/{u_per}, Max: {u_max} {u_cur}/{u_per} (0 means not specified yet).

JOB POSTING:
Title: {title}
Company: {company}
Location: {location}
Source: {job.get('source', '')}
Description:
{description[:10000]}

LOCATION, LANGUAGE & WORK MODE RULES:
- Candidate lives in {cand_loc}.
- Prioritize jobs in the candidate's home country/region and prefer **{pref_lang.upper()}** as the primary language.
- Highest priority: Local metro area + Hybrid.
- Second priority: Home country / Local + Remote.
- Third priority: International + Remote ONLY (rank slightly lower than equivalent local roles).
- International jobs that are NOT remote (on-site or hybrid outside the candidate's country) MUST receive a low match_score (<= 20).
- Allowed application languages: Portuguese ("pt"), English ("en"), Italian ("it").

HUMAN & CULTURAL FIT SCORING RULES:
- Evaluate how well the company's mission, culture, leadership style, and industry align with the candidate's Personal Positioning and Culture & Values — not just job title keywords.
- Reward roles that match their preferred skills/domains and leadership/work style.
- If the job clearly hits one of the candidate's Dealbreakers, reduce match_score significantly and explicitly call out the dealbreaker in match_reason.

SALARY ESTIMATION RULES:
- If the job description states a salary range, extract it accurately.
- If the job description does NOT state a salary, estimate the realistic market average salary range (min, avg, max) for this exact title, seniority, company tier, and location/market (use BRL monthly for Brazil roles; USD or EUR yearly for international remote roles).

Return ONLY a valid JSON object with these exact keys:
{{
  "language": "pt" | "en" | "it",
  "work_mode": "hybrid" | "remote" | "onsite" | "unknown",
  "is_international": true | false,
  "match_score": 0-100 integer,
  "match_reason": "2-3 concise sentences covering BOTH role/skills fit AND human/cultural alignment (or dealbreaker flags)",
  "missing_skills": "comma-separated list of any notable gaps or dealbreakers, or empty string",
  "estimated_salary_min": integer (0 if impossible to estimate),
  "estimated_salary_avg": integer (market average for this role),
  "estimated_salary_max": integer,
  "estimated_salary_currency": "BRL" | "USD" | "EUR",
  "estimated_salary_period": "monthly" | "yearly",
  "salary_note": "brief 1-sentence note (e.g., 'Posted in JD' or 'Market avg for Sr PM in São Paulo')"
}}
"""
        try:
            raw_text = await self._generate_for_role("matcher", prompt)
            data = _extract_json_block(raw_text or "{}")
            lang = data.get("language", fallback_lang)
            if lang not in ("pt", "en", "it"):
                lang = fallback_lang
            mode = data.get("work_mode", fallback_mode)
            if mode not in ("hybrid", "remote", "onsite", "unknown"):
                mode = fallback_mode
            is_intl = bool(data.get("is_international", fallback_intl))
            tier = compute_priority_tier(location, mode, is_intl)
            score = max(0, min(100, int(data.get("match_score", 50))))
            if is_intl and mode != "remote":
                score = min(score, 20)

            est_min = int(data.get("estimated_salary_min") or 0)
            est_avg = int(data.get("estimated_salary_avg") or 0)
            est_max = int(data.get("estimated_salary_max") or 0)
            if est_avg == 0 and (est_min > 0 or est_max > 0):
                est_avg = int((est_min + est_max) / 2) if (est_min and est_max) else max(est_min, est_max)
            est_cur = str(data.get("estimated_salary_currency") or ("USD" if is_intl else "BRL")).upper()
            est_per = str(data.get("estimated_salary_period") or ("yearly" if is_intl else "monthly")).lower()
            sal_fit = evaluate_salary_fit(est_min, est_avg, est_max, est_cur, est_per, profile)

            return {
                "language": lang,
                "work_mode": mode,
                "is_international": is_intl,
                "match_score": score,
                "priority_tier": tier,
                "match_reason": str(data.get("match_reason", "")).strip(),
                "missing_skills": str(data.get("missing_skills", "")).strip(),
                "estimated_salary_min": est_min,
                "estimated_salary_avg": est_avg,
                "estimated_salary_max": est_max,
                "estimated_salary_currency": est_cur,
                "estimated_salary_period": est_per,
                "salary_fit": sal_fit,
                "salary_note": str(data.get("salary_note", "")).strip(),
            }
        except Exception as exc:
            tier = compute_priority_tier(location, fallback_mode, fallback_intl)
            return {
                "language": fallback_lang,
                "work_mode": fallback_mode,
                "is_international": fallback_intl,
                "match_score": 50 if tier < 5 else 20,
                "priority_tier": tier,
                "match_reason": f"Fallback analysis (Gemini error: {exc})",
                "missing_skills": "",
                "estimated_salary_min": 0,
                "estimated_salary_avg": 0,
                "estimated_salary_max": 0,
                "estimated_salary_currency": "BRL",
                "estimated_salary_period": "monthly",
                "salary_fit": "unknown",
                "salary_note": "",
            }

    async def generate_application_materials(self, job: dict[str, Any]) -> dict[str, str]:
        """Generate a tailored T-Letter and narrative Cover Letter in the job's language (pt/en/it)."""
        lang = job.get("language") or "pt"
        lang_name = {"pt": "Brazilian Portuguese", "en": "English", "it": "Italian"}.get(lang, "Brazilian Portuguese")

        if not await self.has_any_provider():
            raise RuntimeError("No AI provider API key is configured. Add one in Settings first.")

        # Use compact Master Profile context when primary writer is local Ollama so generation is fast & never times out
        writer_candidates = await self._get_role_candidates("writer")
        is_local_writer = bool(writer_candidates and writer_candidates[0].startswith("ollama:"))
        context = await self.build_candidate_context(target_lang=lang, compact=is_local_writer)
        profile = await db.get_profile()
        cand_name = profile.get("full_name") or "the candidate"
        prompt = f"""You are writing tailored job application materials for {cand_name} in {lang_name}.

CANDIDATE PROFILE & T-LETTER STYLE:
{context}

TARGET JOB:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
URL: {job.get('url')}
Description:
{(job.get('description') or '')[:10000]}

INSTRUCTIONS:
1. Write EVERYTHING strictly in {lang_name}.
2. Produce two artifacts:
   - "t_letter": A signature T-Letter format: warm executive greeting, 2-sentence intro, Markdown 2-column table mapping 6-8 key job requirements to the candidate's concrete, quantified experiences (never fabricate metrics; only use facts from their profile), and their contact sign-off.
   - "cover_letter": A crisp, persuasive 3-paragraph executive cover letter tailored to this exact company and role, ending with the candidate's contact sign-off.

Return ONLY a valid JSON object:
{{
  "t_letter": "...",
  "cover_letter": "..."
}}
"""
        raw_text = await self._generate_for_role("writer", prompt)
        data = _extract_json_block(raw_text or "{}")
        return {
            "t_letter": str(data.get("t_letter", "")).strip(),
            "cover_letter": str(data.get("cover_letter", "")).strip(),
        }

    async def answer_form_questions(
        self,
        job: dict[str, Any],
        fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Answer structured application form fields in the job's language.
        Each field: {"id": str, "label": str, "type": "text"|"textarea"|"select"|"radio"|"checkbox"|"number", "options": [...], "required": bool}
        Returns: {"answers": {field_id: value}, "needs_human": [field_id, ...], "reason": str}
        """
        lang = job.get("language") or "pt"
        lang_name = {"pt": "Brazilian Portuguese", "en": "English", "it": "Italian"}.get(lang, "Brazilian Portuguese")
        if not await self.has_any_provider():
            return {"answers": {}, "needs_human": [f["id"] for f in fields if f.get("required")], "reason": "No AI provider API key configured"}

        profile = await db.get_profile()
        context = await self.build_candidate_context(target_lang=lang)
        est_avg = job.get("estimated_salary_avg") or 0
        est_cur = job.get("estimated_salary_currency") or "BRL"
        est_per = job.get("estimated_salary_period") or "monthly"
        u_min = profile.get("salary_min") or 0
        u_max = profile.get("salary_max") or 0
        u_cur = profile.get("salary_currency") or "BRL"
        u_per = profile.get("salary_period") or "monthly"

        cand_name = profile.get("full_name") or "the candidate"
        prompt = f"""You are filling out a job application form on behalf of {cand_name}.
Respond strictly in {lang_name} (except for exact option text that must match one of the provided options).

CANDIDATE PROFILE:
{context}

JOB:
{job.get('title')} at {job.get('company')} ({job.get('location')})
Estimated Market Average Salary for this role: {est_avg} {est_cur}/{est_per}
Candidate Target Salary Range: {u_min} - {u_max} {u_cur}/{u_per}

FORM FIELDS TO FILL (JSON):
{json.dumps(fields, ensure_ascii=False, indent=2)}

RULES:
- For "select" or "radio" fields, your answer MUST match one of the provided "options" verbatim.
- If a field asks where/how the candidate heard about this position (referral/source dropdown or text), ALWAYS answer "LinkedIn" (or select the exact option containing "LinkedIn").
- For phone number fields on Brazilian jobs, ALWAYS exclude the "+55" country code and use the national format (DDD + number).
- For "number" fields (e.g. years of experience), return ONLY a plain integer string like "13" or "8".
- For salary expectation fields ("Pretensão salarial", "Salary expectation", "Aspettativa salariale"): use the realistic market average salary for this position ({est_avg} {est_cur}/{est_per} if > 0, otherwise estimate the market average for this role), ensuring it is at least the candidate's minimum ({u_min} {u_cur}/{u_per}) if a minimum is configured. Return plain numbers if the field type is "number".
- For "checkbox" fields (terms/privacy/consent), return true only for standard privacy/consent; if unsure, put the field id in "needs_human".
- NEVER fabricate sensitive personal IDs (CPF, RG, passport, date of birth, exact street address). If a required field asks for sensitive/unknown info, put its "id" in "needs_human" and omit it from "answers".
- Keep text answers concise, accurate, and tailored to the job.

Return ONLY a valid JSON object:
{{
  "answers": {{"field_id": "value"}},
  "needs_human": ["field_id_if_any"],
  "reason": "brief note if needs_human is non-empty"
}}
"""
        raw_text = await self._generate_for_role("form", prompt)
        data = _extract_json_block(raw_text or "{}")
        return {
            "answers": data.get("answers", {}),
            "needs_human": data.get("needs_human", []),
            "reason": str(data.get("reason", "")),
        }

    async def extract_profile_from_documents(self, language: str = "pt") -> dict[str, str]:
        """
        Parse the candidate's uploaded CVs & work-history documents and synthesize
        Executive Summary, Work History, and T-Letter Style & Instructions in EN or PT.
        """
        lang = "en" if (language or "pt").lower() == "en" else "pt"
        lang_name = "English" if lang == "en" else "Brazilian Portuguese"

        if not await self.has_any_provider():
            raise RuntimeError("No AI provider API key is configured. Add one in Settings first.")

        docs = await db.list_documents(include_text=True)
        if not docs:
            raise RuntimeError("No uploaded documents found. Upload your CV or work history files first.")

        # Deduplicate & prioritize documents matching requested language
        seen: set[str] = set()
        unique_docs = []
        for d in docs:
            key = f"{d['language']}:{d['filename']}"
            if key not in seen:
                seen.add(key)
                unique_docs.append(d)

        unique_docs.sort(
            key=lambda d: (
                0 if (d.get("priority") or "primary").lower() == "primary" else 1,
                0 if (d.get("language") or "").lower() == lang else 1,
                0 if d.get("doc_type") == "resume" else 1,
            )
        )

        doc_blocks = []
        for d in unique_docs:
            txt = (d.get("extracted_text") or "").strip()
            if txt:
                p_lbl = "PRIMARY" if (d.get("priority") or "primary").lower() == "primary" else "SECONDARY"
                l_lbl = "EXACT LANGUAGE" if (d.get("language") or "").lower() == lang else "OTHER LANGUAGE"
                doc_blocks.append(
                    f"=== [{p_lbl} REFERENCE | {l_lbl}] {d['filename']} ({d['doc_type']} / {d['language'].upper()}) ===\n{txt[:22000]}"
                )

        if not doc_blocks:
            raise RuntimeError("Uploaded documents contain no extractable text.")

        profile = await db.get_profile()
        cand_name = profile.get("full_name") or "the candidate"
        joined_docs = "\n\n".join(doc_blocks)
        prompt = f"""You are an executive career strategist building a Master Candidate Profile for {cand_name}.
Read ALL uploaded documents below (prioritizing documents marked PRIMARY REFERENCE) and produce a complete, accurate, well-structured profile written STRICTLY in {lang_name}.

UPLOADED DOCUMENTS:
{joined_docs}

INSTRUCTIONS:
1. Write ALL three fields strictly in {lang_name}.
2. NEVER invent metrics, companies, dates, or degrees — only extract facts present in the uploaded documents.
3. Produce a JSON object with these exact 3 keys:
   - "summary": A crisp, high-impact 1-paragraph Executive Summary (4-6 sentences) positioning the candidate's experience, core strengths, education, and languages.
   - "work_history": A clean, well-organized Markdown summary of roles, companies, quantified achievements, education, methodologies, tools, and certifications.
   - "t_letter_examples": Clear T-Letter Style & Instructions in {lang_name} describing the preferred tone, structure (greeting, 2-sentence intro, 2-column Requirement | Experience table mapping job requirements to concrete achievements, honest framing of gaps, and contact sign-off).

Return ONLY a valid JSON object:
{{
  "summary": "...",
  "work_history": "...",
  "t_letter_examples": "..."
}}
"""
        raw_text = await self._generate_for_role("writer", prompt)
        data = _extract_json_block(raw_text or "{}")
        return {
            "summary": str(data.get("summary", "")).strip(),
            "work_history": str(data.get("work_history", "")).strip(),
            "t_letter_examples": str(data.get("t_letter_examples", "")).strip(),
        }

    async def _load_uploaded_docs_only(self, language: str = "pt") -> tuple[str, list[str]]:
        """Return (formatted_text, filenames) strictly from uploaded documents in Profile & CVs."""
        lang = "en" if (language or "pt").lower() == "en" else "pt"
        docs = await db.list_documents(include_text=True)
        if not docs:
            raise RuntimeError("No uploaded documents found. Upload your CV / work history files in 'Profile & CVs' first.")

        seen: set[str] = set()
        unique_docs = []
        for d in docs:
            key = f"{d['language']}:{d['filename']}"
            if key not in seen:
                seen.add(key)
                unique_docs.append(d)

        unique_docs.sort(
            key=lambda d: (
                0 if (d.get("priority") or "primary").lower() == "primary" else 1,
                0 if (d.get("language") or "").lower() == lang else 1,
                0 if d.get("doc_type") == "resume" else 1,
            )
        )

        blocks = []
        filenames = []
        for d in unique_docs:
            txt = (d.get("extracted_text") or "").strip()
            if txt:
                p_lbl = "PRIMARY" if (d.get("priority") or "primary").lower() == "primary" else "SECONDARY"
                l_lbl = (d.get("language") or "pt").upper()
                blocks.append(f"=== [{p_lbl} | {l_lbl}] {d['filename']} ({d['doc_type']}) ===\n{txt[:16000]}")
                filenames.append(f"{d['filename']} ({l_lbl})")

        if not blocks:
            raise RuntimeError("Uploaded documents contain no extractable text.")
        return "\n\n".join(blocks), filenames

    async def extract_peer_search_queries(self, language: str = "pt") -> list[str]:
        """Generate 3 concise LinkedIn People search queries from uploaded CVs to find peers with similar backgrounds."""
        if not await self.has_any_provider():
            return []
        docs_text, _ = await self._load_uploaded_docs_only(language=language)
        prompt = f"""Based ONLY on the uploaded CV/work-history documents below, generate 3 short LinkedIn People search queries (3 to 5 keywords each) to find professionals with a very similar background, skills, and domain so we can see what job titles they use.

DOCUMENTS:
{docs_text[:12000]}

Return ONLY a valid JSON object:
{{"queries": ["query 1", "query 2", "query 3"]}}
"""
        try:
            raw = await self._generate_for_role("matcher", prompt)
            data = _extract_json_block(raw or "{}")
            queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]
            return queries[:3]
        except Exception:
            return []

    async def analyze_cv_documents(
        self,
        language: str = "pt",
        peer_scan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Perform a candid, critical audit strictly from the user's uploaded documents in Profile & CVs,
        enriched with optional LinkedIn peer-title scan results, strictly in EN or PT.
        """
        lang = "en" if (language or "pt").lower() == "en" else "pt"
        lang_name = "English" if lang == "en" else "Brazilian Portuguese"

        if not await self.has_any_provider():
            raise RuntimeError("No AI provider API key or local Ollama server is configured. Set one up in Settings first.")

        docs_text, filenames = await self._load_uploaded_docs_only(language=lang)
        peer_headlines = (peer_scan or {}).get("headlines") or []
        peer_note = (peer_scan or {}).get("note") or ""

        peer_section = (
            "LIVE LINKEDIN PEER HEADLINES (profiles with similar skills/domains):\n"
            + "\n".join(f"- {h}" for h in peer_headlines[:35])
            if peer_headlines
            else f"LIVE LINKEDIN PEER SCAN NOTE: {peer_note or 'No live headlines collected; infer common equivalent LinkedIn titles used by peers with this exact background.'}"
        )

        prompt = f"""You are a candid, senior executive career coach performing a CRITICAL AUDIT of a candidate based SOLELY on their uploaded documents below (do not assume anything outside these documents).

UPLOADED DOCUMENTS:
{docs_text[:26000]}

{peer_section}

INSTRUCTIONS:
1. Write EVERY single field strictly in {lang_name}.
2. Be constructive, specific, and genuinely critical — do not flatter blindly. Call out real gaps (e.g., missing certifications, limited hands-on coding/tooling, unclear metrics, title mismatches, ATS keyword blind spots).
3. Base everything strictly on evidence inside the uploaded documents.
4. Synthesize the LinkedIn peer headlines into concrete, searchable job titles that similar professionals use on LinkedIn.

Return ONLY a valid JSON object with these exact keys:
{{
  "executive_verdict": "2-3 candid sentences summarizing market positioning and competitiveness",
  "main_strengths": ["strength 1 with concrete evidence", "strength 2", "... (5-7 items)"],
  "core_skills": ["skill 1", "skill 2", "... (10-16 concise skill tags)"],
  "suitable_areas": [
    {{"area": "Area / Sector name", "why": "1-2 sentences grounded in the documents"}}
  ],
  "compatible_positions": [
    {{"title": "Exact searchable job title", "fit_level": "High" | "Strong" | "Adjacent", "why": "1-2 sentences"}}
  ],
  "important_gaps": [
    {{"gap": "Specific gap (e.g. missing certification or hands-on experience)", "severity": "High" | "Medium" | "Low", "recommendation": "Actionable way to close or frame this gap"}}
  ],
  "linkedin_peer_titles": [
    {{"title": "Job title used by similar LinkedIn profiles", "insight": "Why peers with this background use this title"}}
  ]
}}
"""
        raw_text = await self._generate_for_role("writer", prompt)
        data = _extract_json_block(raw_text or "{}")
        return {
            "language": lang,
            "analyzed_files": filenames,
            "peer_scan_count": len(peer_headlines),
            "peer_scan_note": peer_note,
            "executive_verdict": str(data.get("executive_verdict", "")).strip(),
            "main_strengths": data.get("main_strengths") or [],
            "core_skills": data.get("core_skills") or [],
            "suitable_areas": data.get("suitable_areas") or [],
            "compatible_positions": data.get("compatible_positions") or [],
            "important_gaps": data.get("important_gaps") or [],
            "linkedin_peer_titles": data.get("linkedin_peer_titles") or [],
        }


ai_engine = AIEngine()

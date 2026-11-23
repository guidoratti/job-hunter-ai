"""SQLite async database layer for Job Hunter AI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.config import DB_PATH
from app.profile_seed import DEFAULT_PROFILE
from app.vault import vault


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'resume',
    language TEXT NOT NULL DEFAULT 'pt',
    priority TEXT NOT NULL DEFAULT 'primary',
    extracted_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    site_domain TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    password_enc TEXT NOT NULL,
    auth_provider TEXT NOT NULL DEFAULT 'standard',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    work_mode TEXT NOT NULL DEFAULT 'unknown',
    is_international INTEGER NOT NULL DEFAULT 0,
    language TEXT NOT NULL DEFAULT 'pt',
    apply_type TEXT NOT NULL DEFAULT 'external',
    url TEXT NOT NULL,
    external_apply_url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    match_score INTEGER NOT NULL DEFAULT 0,
    priority_tier INTEGER NOT NULL DEFAULT 4,
    match_reason TEXT NOT NULL DEFAULT '',
    missing_skills TEXT NOT NULL DEFAULT '',
    estimated_salary_min INTEGER NOT NULL DEFAULT 0,
    estimated_salary_max INTEGER NOT NULL DEFAULT 0,
    estimated_salary_avg INTEGER NOT NULL DEFAULT 0,
    estimated_salary_currency TEXT NOT NULL DEFAULT 'BRL',
    estimated_salary_period TEXT NOT NULL DEFAULT 'monthly',
    salary_fit TEXT NOT NULL DEFAULT 'unknown',
    salary_note TEXT NOT NULL DEFAULT '',
    generated_t_letter TEXT NOT NULL DEFAULT '',
    generated_cover_letter TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    status_note TEXT NOT NULL DEFAULT '',
    selected INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL DEFAULT 'info',
    job_id INTEGER,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


async def _ensure_column(db: aiosqlite.Connection, table: str, col: str, ddl: str) -> None:
    cur = await db.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in await cur.fetchall()}
    if col not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        # Safe migrations for existing databases
        await _ensure_column(db, "documents", "priority", "TEXT NOT NULL DEFAULT 'primary'")
        await _ensure_column(db, "credentials", "auth_provider", "TEXT NOT NULL DEFAULT 'standard'")
        await _ensure_column(db, "jobs", "estimated_salary_min", "INTEGER NOT NULL DEFAULT 0")
        await _ensure_column(db, "jobs", "estimated_salary_max", "INTEGER NOT NULL DEFAULT 0")
        await _ensure_column(db, "jobs", "estimated_salary_avg", "INTEGER NOT NULL DEFAULT 0")
        await _ensure_column(db, "jobs", "estimated_salary_currency", "TEXT NOT NULL DEFAULT 'BRL'")
        await _ensure_column(db, "jobs", "estimated_salary_period", "TEXT NOT NULL DEFAULT 'monthly'")
        await _ensure_column(db, "jobs", "salary_fit", "TEXT NOT NULL DEFAULT 'unknown'")
        await _ensure_column(db, "jobs", "salary_note", "TEXT NOT NULL DEFAULT ''")

        # Seed default profile if missing
        cur = await db.execute("SELECT id FROM profile WHERE id = 1")
        row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO profile (id, data_json, updated_at) VALUES (1, ?, ?)",
                (json.dumps(DEFAULT_PROFILE, ensure_ascii=False), utc_now()),
            )
        await db.commit()


# --- Settings ---

async def set_setting(key: str, value: str, encrypted: bool = False) -> None:
    stored = vault.encrypt(value) if encrypted and value else value
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO settings (key, value, encrypted, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, encrypted=excluded.encrypted, updated_at=excluded.updated_at
            """,
            (key, stored, 1 if encrypted else 0, utc_now()),
        )
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value, encrypted FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        if not row:
            return default
        val, enc = row
        if enc and val:
            try:
                return vault.decrypt(val)
            except Exception:
                return default
        return val


# --- Profile ---

async def get_profile() -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT data_json FROM profile WHERE id = 1")
        row = await cur.fetchone()
        if not row:
            merged = dict(DEFAULT_PROFILE)
        else:
            stored = json.loads(row[0])
            merged = dict(DEFAULT_PROFILE)
            merged.update(stored)

        # Ensure independent per-language storage for PT and EN
        loc = merged.get("localized")
        if not isinstance(loc, dict):
            loc = {}
        pref = (merged.get("preferred_language") or "pt").lower()
        for code in ("pt", "en"):
            if code not in loc or not isinstance(loc[code], dict):
                loc[code] = {
                    "summary": merged.get("summary", "") if code == pref else "",
                    "work_history": merged.get("work_history", "") if code == pref else "",
                    "t_letter_examples": merged.get("t_letter_examples", "") if code == pref else "",
                }
        merged["localized"] = loc
        return merged


async def save_profile(data: dict[str, Any]) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE profile SET data_json = ?, updated_at = ? WHERE id = 1",
            (json.dumps(data, ensure_ascii=False), utc_now()),
        )
        await db.commit()
    return data


# --- Documents ---

async def add_document(
    filename: str,
    stored_path: str,
    doc_type: str,
    language: str,
    extracted_text: str,
) -> dict[str, Any]:
    now = utc_now()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO documents (filename, stored_path, doc_type, language, extracted_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (filename, stored_path, doc_type, language, extracted_text, now),
        )
        doc_id = cur.lastrowid
        await db.commit()
    return {
        "id": doc_id,
        "filename": filename,
        "stored_path": stored_path,
        "doc_type": doc_type,
        "language": language,
        "text_length": len(extracted_text),
        "created_at": now,
    }


async def list_documents(include_text: bool = False) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM documents ORDER BY created_at DESC")
        rows = await cur.fetchall()
        result = []
        for r in rows:
            item = {
                "id": r["id"],
                "filename": r["filename"],
                "stored_path": r["stored_path"],
                "doc_type": r["doc_type"],
                "language": r["language"],
                "priority": r["priority"] if "priority" in r.keys() and r["priority"] else "primary",
                "text_length": len(r["extracted_text"] or ""),
                "created_at": r["created_at"],
            }
            if include_text:
                item["extracted_text"] = r["extracted_text"]
            result.append(item)
        return result


async def update_document_priority(doc_id: int, priority: str) -> None:
    val = "secondary" if (priority or "").lower() == "secondary" else "primary"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE documents SET priority = ? WHERE id = ?", (val, doc_id))
        await db.commit()


async def get_resume_for_language(language: str) -> dict[str, Any] | None:
    """Return best matching resume document for the requested language (pt/en/it), respecting preferred_language fallback."""
    docs = await list_documents(include_text=False)
    resumes = [d for d in docs if d["doc_type"] == "resume"]
    if not resumes:
        return None
    for d in resumes:
        if d["language"].lower() == language.lower():
            return d
    profile = await get_profile()
    pref = (profile.get("preferred_language") or "pt").lower()
    fallback_order = [pref] + [c for c in ("pt", "en", "it") if c != pref]
    for fallback in fallback_order:
        for d in resumes:
            if d["language"].lower() == fallback:
                return d
    return resumes[0]


async def delete_document(doc_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT stored_path FROM documents WHERE id = ?", (doc_id,))
        row = await cur.fetchone()
        if not row:
            return None
        path = row[0]
        await db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        await db.commit()
        return path


# --- Credentials ---

async def upsert_credential(
    site_name: str,
    site_domain: str,
    username: str,
    password: str,
    auth_provider: str = "standard",
    notes: str = "",
) -> dict[str, Any]:
    domain = site_domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
    provider = (auth_provider or "standard").strip().lower()
    enc = vault.encrypt(password)
    now = utc_now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO credentials (site_name, site_domain, username, password_enc, auth_provider, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(site_domain) DO UPDATE SET
                site_name=excluded.site_name,
                username=excluded.username,
                password_enc=CASE WHEN ? != '' THEN excluded.password_enc ELSE credentials.password_enc END,
                auth_provider=excluded.auth_provider,
                notes=excluded.notes,
                updated_at=excluded.updated_at
            """,
            (site_name.strip(), domain, username.strip(), enc, provider, notes.strip(), now, password),
        )
        await db.commit()
    return {
        "site_name": site_name,
        "site_domain": domain,
        "username": username,
        "auth_provider": provider,
        "notes": notes,
        "updated_at": now,
    }


async def list_credentials() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, site_name, site_domain, username, auth_provider, notes, updated_at FROM credentials ORDER BY auth_provider != 'standard' DESC, site_name"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_credential_by_provider(provider: str) -> dict[str, str] | None:
    prov = provider.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM credentials WHERE lower(auth_provider) = ? LIMIT 1", (prov,))
        r = await cur.fetchone()
        if not r:
            return None
        return {
            "site_name": r["site_name"],
            "site_domain": r["site_domain"],
            "username": r["username"],
            "password": vault.decrypt(r["password_enc"]),
            "auth_provider": r["auth_provider"],
            "notes": r["notes"],
        }


async def get_credential_for_url(url: str) -> dict[str, str] | None:
    domain = url.lower().replace("https://", "").replace("http://", "").split("/")[0]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM credentials")
        rows = await cur.fetchall()
        for r in rows:
            stored_domain = r["site_domain"].lower()
            if stored_domain in domain or domain in stored_domain:
                return {
                    "site_name": r["site_name"],
                    "site_domain": r["site_domain"],
                    "username": r["username"],
                    "password": vault.decrypt(r["password_enc"]),
                    "auth_provider": r["auth_provider"],
                    "notes": r["notes"],
                }
    return None


async def delete_credential(cred_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM credentials WHERE id = ?", (cred_id,))
        await db.commit()


# --- Jobs ---

async def upsert_job(job: dict[str, Any]) -> int:
    now = utc_now()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, status FROM jobs WHERE source = ? AND external_id = ?",
            (job["source"], job["external_id"]),
        )
        existing = await cur.fetchone()
        if existing:
            job_id = existing[0]
            await db.execute(
                """
                UPDATE jobs SET
                    title = ?, company = ?, location = ?, work_mode = ?,
                    is_international = ?, language = ?, apply_type = ?,
                    url = ?, external_apply_url = COALESCE(NULLIF(?, ''), external_apply_url),
                    description = CASE WHEN length(?) > length(description) THEN ? ELSE description END,
                    match_score = CASE WHEN ? > 0 THEN ? ELSE match_score END,
                    priority_tier = CASE WHEN ? > 0 THEN ? ELSE priority_tier END,
                    match_reason = CASE WHEN ? != '' THEN ? ELSE match_reason END,
                    missing_skills = CASE WHEN ? != '' THEN ? ELSE missing_skills END,
                    estimated_salary_min = CASE WHEN ? > 0 THEN ? ELSE estimated_salary_min END,
                    estimated_salary_max = CASE WHEN ? > 0 THEN ? ELSE estimated_salary_max END,
                    estimated_salary_avg = CASE WHEN ? > 0 THEN ? ELSE estimated_salary_avg END,
                    estimated_salary_currency = CASE WHEN ? != '' THEN ? ELSE estimated_salary_currency END,
                    estimated_salary_period = CASE WHEN ? != '' THEN ? ELSE estimated_salary_period END,
                    salary_fit = CASE WHEN ? != 'unknown' THEN ? ELSE salary_fit END,
                    salary_note = CASE WHEN ? != '' THEN ? ELSE salary_note END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("work_mode", "unknown"),
                    1 if job.get("is_international") else 0,
                    job.get("language", "pt"),
                    job.get("apply_type", "external"),
                    job.get("url", ""),
                    job.get("external_apply_url", ""),
                    job.get("description", ""),
                    job.get("description", ""),
                    job.get("match_score", 0),
                    job.get("match_score", 0),
                    job.get("priority_tier", 4),
                    job.get("priority_tier", 4),
                    job.get("match_reason", ""),
                    job.get("match_reason", ""),
                    job.get("missing_skills", ""),
                    job.get("missing_skills", ""),
                    int(job.get("estimated_salary_min", 0) or 0),
                    int(job.get("estimated_salary_min", 0) or 0),
                    int(job.get("estimated_salary_max", 0) or 0),
                    int(job.get("estimated_salary_max", 0) or 0),
                    int(job.get("estimated_salary_avg", 0) or 0),
                    int(job.get("estimated_salary_avg", 0) or 0),
                    job.get("estimated_salary_currency", "BRL"),
                    job.get("estimated_salary_currency", "BRL"),
                    job.get("estimated_salary_period", "monthly"),
                    job.get("estimated_salary_period", "monthly"),
                    job.get("salary_fit", "unknown"),
                    job.get("salary_fit", "unknown"),
                    job.get("salary_note", ""),
                    job.get("salary_note", ""),
                    now,
                    job_id,
                ),
            )
            await db.commit()
            return job_id

        cur = await db.execute(
            """
            INSERT INTO jobs (
                source, external_id, title, company, location, work_mode,
                is_international, language, apply_type, url, external_apply_url,
                description, match_score, priority_tier, match_reason, missing_skills,
                estimated_salary_min, estimated_salary_max, estimated_salary_avg,
                estimated_salary_currency, estimated_salary_period, salary_fit, salary_note,
                status, selected, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', 0, ?, ?)
            """,
            (
                job["source"],
                job["external_id"],
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("work_mode", "unknown"),
                1 if job.get("is_international") else 0,
                job.get("language", "pt"),
                job.get("apply_type", "external"),
                job.get("url", ""),
                job.get("external_apply_url", ""),
                job.get("description", ""),
                job.get("match_score", 0),
                job.get("priority_tier", 4),
                job.get("match_reason", ""),
                job.get("missing_skills", ""),
                int(job.get("estimated_salary_min", 0) or 0),
                int(job.get("estimated_salary_max", 0) or 0),
                int(job.get("estimated_salary_avg", 0) or 0),
                job.get("estimated_salary_currency", "BRL"),
                job.get("estimated_salary_period", "monthly"),
                job.get("salary_fit", "unknown"),
                job.get("salary_note", ""),
                now,
                now,
            ),
        )
        await db.commit()
        return int(cur.lastrowid)


async def list_jobs(
    status: str | None = None,
    min_score: int = 0,
    salary_fit: str | None = None,
) -> list[dict[str, Any]]:
    profile = await get_profile()
    pref_lang = (profile.get("preferred_language") or "pt").lower()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        clauses = ["match_score >= ?"]
        params: list[Any] = [min_score]
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if salary_fit and salary_fit != "all":
            if salary_fit == "in_or_above":
                clauses.append("salary_fit IN ('in_range', 'above_range')")
            else:
                clauses.append("salary_fit = ?")
                params.append(salary_fit)
        where = " AND ".join(clauses)
        params.append(pref_lang)
        cur = await db.execute(
            f"""
            SELECT * FROM jobs
            WHERE {where}
            ORDER BY
                match_score DESC,
                is_international ASC,
                CASE WHEN lower(language) = ? THEN 0 ELSE 1 END ASC,
                CASE WHEN source = 'linkedin' THEN 0 ELSE 1 END ASC,
                priority_tier ASC,
                created_at DESC
            """,
            params,
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_dashboard_stats() -> dict[str, Any]:
    """Compute comprehensive performance & pipeline analytics for the Dashboard tab."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM jobs ORDER BY updated_at DESC")
        jobs = [dict(r) for r in await cur.fetchall()]

    total = len(jobs)
    applied = [j for j in jobs if j["status"] == "applied"]
    strong = [j for j in jobs if (j["match_score"] or 0) >= 75]
    in_range = [j for j in jobs if j.get("salary_fit") in ("in_range", "above_range")]
    below_range = [j for j in jobs if j.get("salary_fit") == "below_range"]
    avg_match = round(sum((j["match_score"] or 0) for j in jobs) / total, 1) if total else 0.0
    avg_applied_match = (
        round(sum((j["match_score"] or 0) for j in applied) / len(applied), 1) if applied else 0.0
    )

    def _bucket(key_fn):
        counts: dict[str, dict[str, Any]] = {}
        for j in jobs:
            k = key_fn(j)
            if k not in counts:
                counts[k] = {"label": k, "total": 0, "applied": 0, "score_sum": 0}
            counts[k]["total"] += 1
            counts[k]["score_sum"] += j["match_score"] or 0
            if j["status"] == "applied":
                counts[k]["applied"] += 1
        out = []
        for item in counts.values():
            item["avg_score"] = round(item["score_sum"] / item["total"], 1) if item["total"] else 0
            del item["score_sum"]
            out.append(item)
        out.sort(key=lambda x: (-x["applied"], -x["total"]))
        return out

    def _platform_label(j):
        if j["source"] == "linkedin" and j["apply_type"] == "easy_apply":
            return "LinkedIn Easy Apply"
        if j["source"] == "linkedin":
            return "LinkedIn External"
        if j["source"] == "remotive":
            return "Remotive (Intl Remote)"
        if j["source"] == "indeed":
            return "Indeed"
        if j["source"] == "glassdoor":
            return "Glassdoor"
        if j["source"] == "ziprecruiter":
            return "ZipRecruiter"
        if j["source"] == "gupy":
            return "Gupy"
        return "External / Manual"

    tier_names = {
        1: "P1: SP/Cotia Hybrid",
        2: "P2: Brazil Remote",
        3: "P3: Intl Remote",
        4: "P4: SP On-site / Other",
        5: "P5: Low Location Fit",
    }

    return {
        "summary": {
            "total_jobs": total,
            "applied_count": len(applied),
            "new_count": sum(1 for j in jobs if j["status"] == "new"),
            "needs_action_count": sum(1 for j in jobs if j["status"] == "needs_action"),
            "skipped_count": sum(1 for j in jobs if j["status"] == "skipped"),
            "failed_count": sum(1 for j in jobs if j["status"] == "failed"),
            "strong_matches": len(strong),
            "in_range_salary": len(in_range),
            "below_range_salary": len(below_range),
            "avg_match_score": avg_match,
            "avg_applied_match_score": avg_applied_match,
            "apply_rate_pct": round((len(applied) / total) * 100, 1) if total else 0.0,
        },
        "by_platform": _bucket(_platform_label),
        "by_status": _bucket(lambda j: j["status"]),
        "by_language": _bucket(lambda j: (j["language"] or "pt").upper()),
        "by_priority": _bucket(lambda j: tier_names.get(j["priority_tier"], f"P{j['priority_tier']}")),
        "by_salary_fit": _bucket(lambda j: j.get("salary_fit") or "unknown"),
        "by_work_mode": _bucket(lambda j: j.get("work_mode") or "unknown"),
        "top_companies": _bucket(lambda j: j["company"] or "Unknown")[:12],
        "top_positions": _bucket(lambda j: j["title"] or "Unknown")[:12],
        "recent_applications": [
            {
                "id": j["id"],
                "title": j["title"],
                "company": j["company"],
                "platform": _platform_label(j),
                "language": (j["language"] or "pt").upper(),
                "match_score": j["match_score"],
                "estimated_salary_avg": j.get("estimated_salary_avg", 0),
                "estimated_salary_currency": j.get("estimated_salary_currency", "BRL"),
                "estimated_salary_period": j.get("estimated_salary_period", "monthly"),
                "salary_fit": j.get("salary_fit", "unknown"),
                "status": j["status"],
                "updated_at": j["updated_at"],
                "url": j["url"],
            }
            for j in jobs[:25]
        ],
    }


async def get_job(job_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = utc_now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
        await db.commit()


async def delete_job(job_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        await db.commit()


async def clear_all_jobs() -> int:
    """Clear all indexed jobs/application statistics while preserving profile, CVs, credentials, and settings."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM jobs")
        row = await cur.fetchone()
        count = int(row[0]) if row else 0
        await db.execute("DELETE FROM jobs")
        await db.commit()
        return count


BLANK_PROFILE = {
    "full_name": "",
    "email": "",
    "phone": "",
    "linkedin_url": "",
    "city": "",
    "state": "",
    "country": "",
    "preferred_language": "pt",
    "target_roles": [],
    "languages": [],
    "location_preferences": {
        "primary_cities": [],
        "local_modality_priority": ["hybrid", "remote", "onsite"],
        "international_modality": "remote_only",
        "allowed_languages": ["pt", "en", "it"],
    },
    "salary_expectation": "",
    "salary_min": 0,
    "salary_max": 0,
    "salary_currency": "BRL",
    "salary_period": "monthly",
    "notice_period": "",
    "match_preferences": {
        "skills": "",
        "industries": "",
        "seniority": "Any Seniority",
        "culture_values": "",
        "personal_positioning": "",
        "dealbreakers": "",
    },
    "summary": "",
    "work_history": "",
    "t_letter_examples": "",
    "localized": {
        "pt": {"summary": "", "work_history": "", "t_letter_examples": ""},
        "en": {"summary": "", "work_history": "", "t_letter_examples": ""},
    },
}


async def nuclear_reset_db() -> None:
    """Erase all jobs, documents, credentials, settings, logs, and scrub profile to blank."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM jobs")
        await db.execute("DELETE FROM documents")
        await db.execute("DELETE FROM credentials")
        await db.execute("DELETE FROM settings")
        await db.execute("DELETE FROM activity_logs")
        await db.execute(
            "UPDATE profile SET data_json = ?, updated_at = ? WHERE id = 1",
            (json.dumps(BLANK_PROFILE, ensure_ascii=False), utc_now()),
        )
        await db.commit()


# --- Logs ---

async def add_log(message: str, level: str = "info", job_id: int | None = None) -> dict[str, Any]:
    now = utc_now()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO activity_logs (level, job_id, message, created_at) VALUES (?, ?, ?, ?)",
            (level, job_id, message, now),
        )
        await db.commit()
        return {"id": cur.lastrowid, "level": level, "job_id": job_id, "message": message, "created_at": now}


async def list_logs(limit: int = 100) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

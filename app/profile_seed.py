"""Default starter profile template for new Job Hunter AI installations."""

DEFAULT_PROFILE = {
    "full_name": "",
    "email": "",
    "phone": "",
    "linkedin_url": "",
    "city": "",
    "state": "",
    "country": "",
    "preferred_language": "pt",
    "target_roles": [],
    "languages": [
        {"language": "Portuguese", "code": "pt", "level": "Native"},
        {"language": "English", "code": "en", "level": "Fluent"},
    ],
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
    "notice_period": "Negotiable",
    "match_preferences": {
        "search_keywords": "Product Manager, Engineering Manager, Tech Manager",
        "search_locations": "São Paulo, Brazil; Remote; Europe; United States",
        "skills": "",
        "industries": "",
        "seniority": "Any Seniority",
        "culture_values": "",
        "personal_positioning": "",
        "dealbreakers": "",
    },
    "summary": "",
    "work_history": "",
    "t_letter_examples": """### Signature T-Letter Style
A T-Letter is a concise, high-impact executive introduction:
1. Warm greeting referencing the exact job title and company.
2. Short 2-3 sentence positioning paragraph summarizing years of experience and core impact.
3. A 2-column Markdown table (`Position Requirements | Experiences` in EN, `Requisitos da Posição | Experiências` in PT, `Requisiti della Posizione | Esperienze` in IT) mapping 6-8 key requirements from the job description to concrete, quantified achievements from the candidate's profile.
4. Honest framing when a niche requirement is not directly held.
5. Professional sign-off with name, phone, email, and LinkedIn URL.
""",
    "localized": {
        "pt": {"summary": "", "work_history": "", "t_letter_examples": ""},
        "en": {"summary": "", "work_history": "", "t_letter_examples": ""},
    },
}

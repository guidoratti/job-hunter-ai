# 🎯 Job Hunter AI

> *Automating the boring stuff since five minutes ago.*

An open-source, **local-first** web application (Python + FastAPI + Playwright + Multi-Agent AI) that searches, scores, prioritizes, and helps automatically apply for jobs across **LinkedIn** (Easy Apply + External ATS links), **Indeed**, **Glassdoor**, **ZipRecruiter**, and **Remotive** — with a background persistent browser and human-in-the-loop roadblock handling.

---

## Key Features

- **Multi-Platform Job Discovery (Capped at 50 Jobs or 5 Minutes per Search)**:
  - Searches **LinkedIn** (primary), **Indeed**, **Glassdoor**, **ZipRecruiter**, and **Remotive (Intl Remote)** with a live countdown timer, progress bar, and instant **🛑 STOP** button.
  - Supports **Human Fit, Skills, Culture, Seniority (multi-select), Personal Positioning, and Dealbreakers** — going well beyond simple job-title keywords.
- **Multi-Vendor & 100% Free Local AI (Multi-Agent Routing)**:
  - Route each specialized agent independently:
    - **🔍 Scout / Matcher Agent**: Role + cultural fit scoring & market average salary estimation.
    - **✍️ Writer Agent**: Tailored **T-Letters** (`Requirement | Experience` table), **Cover Letters**, and **EN / PT Master Profile** extraction from uploaded CVs.
    - **📝 Form-Filler Agent**: Automatically answers screening questions and fills LinkedIn Easy Apply, Gupy, Workday, Greenhouse, Lever, and generic external ATS forms.
    - **🛡️ Cross-Vendor Fallback Model**: Automatic failover if a vendor hits a rate limit or `503`.
  - Supports **🦙 Local Ollama (100% Free & Offline)** with one-click **⚡ Setup Local Server**, **OpenRouter (`:free` + Paid)**, **Google Gemini**, **OpenAI**, and **Anthropic Claude**.
- **Salary Range Intelligence**:
  - Set your Min/Max target salary (BRL / USD / EUR, Monthly / Yearly). AI estimates each role's market average, marks jobs as **In Range / Above Range / Below Range**, and uses market averages when filling forms.
- **Trilingual Support (`PT` / `EN` / `IT`), Per-Language Profiles & Critical CV Analysis**:
  - Detects each job's language automatically, attaches the matching CV, and maintains independent editable **EN** and **PT** Master Candidate Profiles.
  - Built-in **🔬 CV Analysis** tab audits solely your uploaded documents to surface strengths, core skills, suitable areas, compatible positions, critical gaps, and LinkedIn peer job titles (3-minute scan).
  - On-demand **✨ GenAI** T-Letter & Cover Letter (≤ 850 chars, first-person, document-only) with mandatory user approval before submission.
- **Background Persistent Browser + SSO Sessions + Roadblock Pause/Resume**:
  - Runs Chrome/Edge minimized in the background (with **👁️ Show Browser** / **➖ Hide** toggles).
  - Connect **Google, LinkedIn, Microsoft, or Discord SSO** via persistent browser cookies.
  - Automatically pauses and prompts you whenever a site requires login, account creation, 2FA, CAPTCHA, or unknown required fields.
- **Analytics Dashboard & Privacy-First Local Storage**:
  - Track applications, match scores, platforms, salary fit, top companies, and top roles in the **📊 Dashboard** tab.
  - All personal data, CVs, encrypted credentials (`data/.vault.key`), and browser sessions stay strictly local (excluded by `.gitignore`), with a double-confirmed **☢️ Nuclear Reset** button to wipe everything clean.

---

## Quick Start

### One-Command Installers *(Easiest!)*

- **Windows (PowerShell)**:
  ```powershell
  irm https://raw.githubusercontent.com/guidoratti/job-hunter-ai/main/install.ps1 | iex
  ```
  *(Automatically installs Git & Python 3.12 if needed, downloads Job Hunter AI to `%USERPROFILE%\JobHunterAI`, installs dependencies + Chromium, and creates a **Job Hunter AI** Start Menu shortcut!)*

- **macOS / Linux (Terminal)**:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/guidoratti/job-hunter-ai/main/install.sh | bash
  ```
  *(Downloads Job Hunter AI to `~/JobHunterAI`, installs dependencies + Chromium, and creates a double-clickable **Job Hunter AI.command** launcher on macOS Desktop or a Linux desktop shortcut!)*

---

### Manual Install

#### Prerequisites
- **Python 3.10+** (`winget install Python.Python.3.12` on Windows, `brew install python@3.12` on macOS, or [python.org](https://www.python.org/downloads/) — Python 3.9 on macOS is also supported automatically via `eval_type_backport`)
- **Google Chrome** or **Microsoft Edge** (used for persistent browser automation)
- Either **Ollama** ([ollama.com/download](https://ollama.com/download)) for 100% free local AI **or** an API key from **OpenRouter / Google Gemini / OpenAI / Anthropic**.

#### Windows
```powershell
git clone https://github.com/guidoratti/job-hunter-ai.git
cd job-hunter-ai
.\setup.bat
.\run.bat
```
*(Double-clicking `setup.bat` then `run.bat` also works!)*

#### macOS / Linux
```bash
git clone https://github.com/guidoratti/job-hunter-ai.git
cd job-hunter-ai
chmod +x setup.sh run.sh
./setup.sh
./run.sh
```

The dashboard opens automatically at **`http://127.0.0.1:8000`**.

---

## First-Time Setup in the UI (Step-by-Step)

### 1. Configure Your AI Engine (**Settings & Live Logs** tab)
Pick **Option A (100% Free Local AI)** or **Option B (Cloud API)** — or use both with automatic failover:

- **Option A — 🦙 100% Free Local AI via Ollama (Recommended if you have an 8GB+ VRAM GPU)**:
  1. Click **⬇️ Install ↗** (or download from [ollama.com/download](https://ollama.com/download)) and run the installer.
  2. Back in **Job Hunter AI**, click **⚡ Setup Local Server**.
  3. It automatically starts Ollama in the background, downloads `qwen2.5:7b` (fast Scout/Matcher & Form-Filler) and `gemma3:12b` (high-quality Writer), and configures all agents for you.
  4. Once ready, the button turns into **`✅ Local Server Running`**.
- **Option B — Cloud AI (OpenRouter / Gemini / OpenAI / Anthropic)**:
  1. Click **🔑 Key ↗** next to your preferred vendor to generate an API key (and **💳 Billing ↗** if you need to add credits).
     - **OpenRouter** works with **\$0 free-tier (`:free`) models** or ~\$5 in credits for 100+ models under one key.
     - **Note on Google Gemini**: Consumer *Google AI Pro/Ultra* subscriptions are separate from the *Google AI Studio* Developer API. Free-tier keys have a low daily limit; enabling Pay-as-you-go billing on [aistudio.google.com/billing](https://aistudio.google.com/billing) costs pennies per search.
  2. Paste your key, click **💾 Save Settings**, then click **🧪 Test** to verify connectivity.
  3. Under **🤖 Multi-Agent Model Routing**, pick a model for each agent (look for the **`⭐ (Recommended)`** tags!) and optionally set a **🛡️ Cross-Vendor Fallback Model**.

### 2. Upload Your CVs & Build Your Master Profile (**Profile & CVs** tab)
1. Upload your resume(s) in PDF, DOCX, or TXT (tagged `PT`, `EN`, or `IT`) and any extra work-history or T-Letter documents.
2. Set each file's **Reference Priority** (`Primary` / `Secondary`) using the dropdown in the table.
3. On **Master Candidate Profile**, select **`PT`** or **`EN`** and click **⚙️ Process** — the Writer Agent extracts your **Executive Summary**, **Work History**, and **T-Letter Style** in that language.
   - Switch between **`EN`** and **`PT`** to maintain independent tailored profiles for each language.
   - All fields remain editable and **auto-save** automatically as you type.
4. Fill in your **Target Salary (Min / Max)**, Currency (`BRL`/`USD`/`EUR`), and Period (`Monthly`/`Yearly`).

### 3. Run a Critical CV Audit (**🔬 CV Analysis** tab)
1. Open the **🔬 CV Analysis** tab — this tool analyzes **solely the documents you uploaded** in *Profile & CVs* (respecting your Primary / Secondary Reference Priority).
2. Choose **`PT`** (Brazilian Portuguese) or **`EN`** (English) using the toggle in the top-right corner, then click **🔍 Run Check**.
   - Both the AI analysis and all section headings are generated strictly in the selected language, and **PT** and **EN** audits are saved independently.
3. Wait for the live **3-minute progress bar** as the tool:
   - Scans LinkedIn People (strictly capped at 3 minutes) to discover what job titles real professionals with similar CVs are using.
   - Generates a candid executive audit covering:
     - **Executive Audit Verdict**
     - **💪 Main Strengths** (grounded in concrete evidence from your files)
     - **🧠 Core Skills**
     - **🏢 Most Suitable Areas of Work**
     - **🎯 Most Compatible Job Positions**
     - **⚠️ Important Gaps & Recommendations** (missing certifications, hands-on gaps, etc., ranked High / Medium / Low)
     - **🔎 LinkedIn Peer Titles (3-Min Market Scan)**
4. Click **`+ Add to Search`** (or **`+ Adicionar à Busca`**) next to any compatible position or LinkedIn peer title to add it straight into your **Target Job Titles / Keywords** box.

### 4. Connect Your Job Platforms (**Auto-Fill & Credential Vault** tab)
1. Click **🔵 Google SSO**, **💼 LinkedIn SSO**, **🪟 Microsoft SSO**, or **🎮 Discord SSO**.
2. The minibrowser opens directly to that platform's login page. Sign in once (including any 2FA) — your session cookies are saved automatically in the persistent Chrome profile.
3. Once validated, the button turns greyed-out (**`✅ Validated`**) and only unlocks if your session ever expires or is revoked.
4. Optionally store traditional email/password logins for ATS portals (like Gupy or Workday) — encrypted locally with AES-256.

### 5. Search, Match & Apply (**Jobs & Apply Queue** tab)
1. Edit **Target Job Titles / Keywords**, **Locations**, and open **🧭 Human Fit, Skills, Culture & Personal Positioning** to set your skills, industries, multi-select seniority, culture values, personal positioning, and dealbreakers (everything auto-saves).
2. Check the platforms you want to search (**LinkedIn** always runs first), then click **🔍 Search & Score Jobs** (or **🔄 Refresh Search** to clear old listings first).
   - Searches are capped at **50 jobs or 5 minutes** with a live countdown bar and a **🛑 STOP** button.
   - Watch real-time progress in the **🤖 Live Agent Activity** panel (click **👁️ Watch in Browser** anytime to view the background browser).
3. Review your ranked matches (sorted highest Match Score first, with 💰 Salary Range fit badges). Click **📝 T-Letter & Cover Letter** on any job and use the **✨ GenAI** buttons to generate fresh first-person T-Letters or Cover Letters (≤ 850 chars) on demand.
4. Check the jobs you want and click **🚀 Apply to Selected** (or **⚡ Apply to All**).
   - Letters are only auto-generated if the application form actually demands one — and the tool **always pauses for your approval** before submitting any application with a letter.
   - Keep **Auto-Submit** unchecked to review each form before final submission, or check it to submit automatically unless a login/CAPTCHA/letter/unknown-field roadblock appears.

### 6. Track Performance (**📊 Dashboard** tab)
- View KPIs, match-score averages, platform/status/salary breakdowns, top companies, and top roles.
- Use **🗑️ Clear Statistics** when tuning preferences to measure fresh results, or **☢️ Nuclear Reset** (in **Settings & Live Logs**) to scrub all personal data cleanly.

---

## Troubleshooting

| Issue | Fix |
| :--- | :--- |
| **`Failed to fetch` / cannot connect to `127.0.0.1:8000`** | Make sure the terminal window started by `run.bat` / `./run.sh` is still open and running. |
| **Windows blocks `setup.ps1` / `run.ps1`** | Use **`setup.bat`** and **`run.bat`** instead — they bypass PowerShell's execution policy automatically. |
| **Local Ollama is slow** | Use `qwen2.5:7b` or `llama3.1:8b` (fits inside 8 GB VRAM) for Scout/Form-Filler, or switch to an OpenRouter / Gemini cloud model if your machine has no dedicated GPU. |
| **A site asks for login or CAPTCHA** | Job Hunter AI intentionally **never bypasses CAPTCHAs**. It pauses cleanly, pops up the minibrowser, and waits for you to complete the check and click **✅ Done — Resume Automation**. |
| **Want to start completely fresh / hand off PC** | Go to **Settings & Live Logs** → scroll below Live Activity Log → click **☢️ Nuclear Reset** (double-confirmed). |

---

## Project Structure

```
job-hunter/
├── app/
│   ├── main.py              # FastAPI server, SSE live events & REST API
│   ├── ai_engine.py         # Multi-vendor & multi-agent AI router (Ollama, Gemini, OpenAI, Claude, OpenRouter)
│   ├── browser_manager.py   # Persistent Playwright Chrome/Edge manager & Roadblock pause/resume
│   ├── database.py          # Async SQLite storage & Dashboard analytics
│   ├── vault.py             # Local AES-256 (Fernet) credential encryption
│   ├── document_parser.py   # PDF / DOCX / TXT text extractor
│   ├── scrapers/            # LinkedIn, Indeed, Glassdoor, ZipRecruiter, Remotive
│   └── appliers/            # LinkedIn Easy Apply, External ATS (Gupy, Workday, Greenhouse, Lever) & Form Filler
├── static/                  # Vanilla HTML / CSS / JS dashboard (zero build step)
├── run_server.py            # Windows ProactorEventLoop-safe Uvicorn launcher
├── setup.bat / run.bat      # Windows one-click setup & launch
└── setup.sh / run.sh        # macOS / Linux setup & launch
```

---

## Contributing

Contributions are very welcome! Ideas for PRs:
- Additional ATS form adapters (Workday multi-page flows, Ashby, SmartRecruiters, Lever)
- Additional regional job board scrapers
- Improved CV/resume tailoring & export to PDF
- Unit & integration tests for scrapers and form fillers

Please open an issue or pull request — and make sure never to commit anything inside `data/`.

## License

[MIT](LICENSE)

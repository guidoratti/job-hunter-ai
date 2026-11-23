/* Job Hunter AI Frontend */
let jobsCache = [];
let profileCache = {};

const BRAND_TAGLINES = [
  // User originals
  "We fight bots with AI agents!",
  "Want me to apply for 100+ jobs? Just you wait for it!",
  "Ain't nobody got time for manual form filling.",
  "It's their AI against my AI agents, buddy.",
  "Don't do by hand what my AI agent can do for you.",
  "3... 2... 1... GO! Bring me them jobs!",
  "I could be playing GTA VI too, you know...",
  "By the power of AI agents... I HAVE THE POWER!",
  "Your friendly AI agent, SpiderAI. Nah, didn't work.",
  // 50+ fresh sarcastic / light-humor taglines
  "Upload CV, re-type entire CV into 47 boxes? Not today.",
  "My AI agent eats ATS filters for breakfast.",
  "Because 'please create an account to apply' is a crime.",
  "Putting the 'auto' in 'automatically hired'.",
  "If their recruiter is a bot, mine should be smarter.",
  "Zero cover-letter writer's block. 100% pure caffeine.",
  "Teaching robots to beg for interviews so you don't have to.",
  "Workday forms fear this browser.",
  "I'd rather be flying a MISC Prospector, honestly.",
  "Applying at warp speed. Engage!",
  "Dear HR bot, please meet my career bot.",
  "One click for man, 100 applications for mankind.",
  "Turning 'we'll keep your CV on file' into actual interviews.",
  "No more copy-pasting your own phone number 90 times.",
  "May the ATS odds be ever in your favor.",
  "Deploying tactical T-Letters in 3 languages.",
  "Trilingual AI hustle: PT, EN, and IT without breaking a sweat.",
  "Your keyboard called — it says thank you.",
  "Automated job hunting: because sleep is also nice.",
  "HR uses AI to reject. We use AI to reply. Fair game.",
  "Not all heroes wear capes. Some run Playwright.",
  "Looking for a job is a full-time job — so I hired an AI.",
  "Hybrid nearby or remote worldwide. No exceptions, boss.",
  "Still faster than waiting for a recruiter to reply.",
  "Ctrl+C, Ctrl+V? How delightfully 2012.",
  "Warning: may cause sudden calendar invites from recruiters.",
  "Built with Python, coffee, and mild annoyance at job portals.",
  "Automating the boring stuff since five minutes ago.",
  "Let's see how their screening bot handles THIS T-Letter.",
  "Saving your wrists from endless 'Next > Next > Submit' clicks.",
  "Yes, I have years of experience. Stop asking on every page.",
  "If it takes 12 clicks to apply, let the bot click them.",
  "Out-automating the automated rejection machine.",
  "Your personal career wingman — zero small talk required.",
  "Loading dream job... please do not turn off your console.",
  "Press X to doubt 'competitive salary' with no number listed.",
  "Estimating salaries so you don't waste an hour on a lowball.",
  "Job portals hate this one weird local Python script.",
  "Now with 100% fewer 're-enter your work history' tears.",
  "Making job hunting slightly less painful, one click at a time.",
  "Somewhere, an ATS algorithm just felt a disturbance in the Force.",
  "No CAPTCHA bypassed, just pure, legal, caffeinated efficiency.",
  "Because 'Easy Apply' is rarely actually easy.",
  "Hunting roles with 99.997% availability.",
  "Sip your coffee. The agent's got the clipboard.",
  "Why fill 10 forms when one agent can do it in the background?",
  "Professional bridge between tech, business, and not losing your mind.",
  "Bringing executive energy to automated form filling.",
  "Plot twist: the AI agent actually reads the job description.",
  "Ready to turn LinkedIn scrolling into actual offers.",
  "Less form-filling, more interviewing (and maybe some gaming).",
  "Mission: find a great company. Status: agents deployed.",
];

function pickRandomTagline() {
  const el = document.getElementById("brandTagline");
  if (!el || !BRAND_TAGLINES.length) return;
  const lastIdx = parseInt(localStorage.getItem("jh_last_tagline_idx") || "-1", 10);
  let idx = Math.floor(Math.random() * BRAND_TAGLINES.length);
  if (BRAND_TAGLINES.length > 1 && idx === lastIdx) {
    idx = (idx + 1) % BRAND_TAGLINES.length;
  }
  localStorage.setItem("jh_last_tagline_idx", String(idx));
  el.textContent = BRAND_TAGLINES[idx];
}

const TIER_LABELS = {
  1: "P1: SP/Cotia Hybrid",
  2: "P2: Brazil Remote",
  3: "P3: Intl Remote",
  4: "P4: SP On-site / Other",
  5: "P5: Low Location Fit",
};

// --- Tabs ---
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

async function api(url, opts = {}) {
  let res;
  try {
    res = await fetch(url, opts);
  } catch (err) {
    throw new Error("Cannot reach the Job Hunter AI server (http://127.0.0.1:8000). Launch 'Job Hunter AI' from your Windows Start Menu first.");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const err = await res.json();
      msg = err.detail || JSON.stringify(err);
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

// --- SSE Live Events ---
function connectSSE() {
  const es = new EventSource("/api/events");
  es.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "state") {
        updateRunnerStatus(msg.data.runner);
        if (msg.data.roadblock) showRoadblock(msg.data.roadblock);
        if (msg.data.search_progress) updateSearchProgress(msg.data.search_progress);
      } else if (msg.type === "runner_state") {
        updateRunnerStatus(msg.data);
        loadJobs();
      } else if (msg.type === "search_progress") {
        updateSearchProgress(msg.data);
      } else if (msg.type === "sso_status") {
        renderSsoStatus(msg.data);
      } else if (msg.type === "cv_analysis_progress") {
        updateCvAnalysisProgress(msg.data);
      } else if (msg.type === "cv_analysis_done") {
        if (msg.data?.language && msg.data?.result) {
          cvAnalysisCache[msg.data.language] = msg.data.result;
          if (cvAnalysisLang === msg.data.language) renderCvAnalysis();
        }
        setCvRunButtonState(false);
      } else if (msg.type === "cv_analysis_error") {
        setCvRunButtonState(false);
        alert("CV Analysis failed: " + (msg.data?.error || "Unknown error"));
      } else if (msg.type === "roadblock") {
        showRoadblock(msg.data);
      } else if (msg.type === "roadblock_cleared") {
        hideRoadblock();
        loadJobs();
      } else if (msg.type === "job_added") {
        loadJobs();
      } else if (msg.type === "log") {
        appendLog(msg.data);
      }
    } catch {}
  };
  es.onerror = () => {
    es.close();
    setTimeout(connectSSE, 3000);
  };
}

let isApplying = false;
let currentApplyingJobId = null;
let searchCountdownTimer = null;
let lastSearchProgress = null;

function formatCountdown(deadlineTs) {
  if (!deadlineTs) return "05:00";
  const rem = Math.max(0, Math.ceil(deadlineTs - Date.now() / 1000));
  const mm = String(Math.floor(rem / 60)).padStart(2, "0");
  const ss = String(rem % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function renderSearchProgressDisplay(p) {
  const box = document.getElementById("searchProgressBox");
  const label = document.getElementById("searchProgressLabel");
  const count = document.getElementById("searchProgressCount");
  const fill = document.getElementById("searchProgressFill");
  if (!box || !p) return;

  if (!p.active && !p.indexed) {
    box.classList.remove("visible");
    return;
  }
  box.classList.add("visible");
  const maxT = p.max_total || 50;
  const pct = p.percent || 0;
  if (p.active) {
    const queryPart = p.current_query ? ` — ${p.current_query}` : "";
    label.textContent = `Searching & Matching: ${p.current_platform || "Running…"}${queryPart}`;
    fill.classList.remove("done");
    const timerStr = formatCountdown(p.deadline_ts);
    count.textContent = `⏱️ ${timerStr} left • ${p.indexed} / ${maxT} jobs (${pct}%)`;
  } else {
    const reason = p.stop_reason ? ` (${p.stop_reason})` : "";
    label.textContent = `✅ Search complete — ${p.indexed} job(s) analyzed & ranked${reason}`;
    fill.classList.add("done");
    count.textContent = `⏱️ 00:00 • ${p.indexed} / ${maxT} jobs (${pct}%)`;
  }
  fill.style.width = `${Math.max(p.active ? 4 : 0, pct)}%`;
}

function updateSearchProgress(p) {
  lastSearchProgress = p;
  renderSearchProgressDisplay(p);
  if (searchCountdownTimer) {
    clearInterval(searchCountdownTimer);
    searchCountdownTimer = null;
  }
  if (p && p.active && p.deadline_ts) {
    searchCountdownTimer = setInterval(() => {
      if (!lastSearchProgress || !lastSearchProgress.active) {
        clearInterval(searchCountdownTimer);
        searchCountdownTimer = null;
        return;
      }
      renderSearchProgressDisplay(lastSearchProgress);
    }, 1000);
  }
}

function setAllApplyButtonsDisabled(disabled) {
  const applyBtn = document.getElementById("applySelectedBtn");
  const applyAllBtn = document.getElementById("applyAllBtn");
  if (applyBtn) applyBtn.disabled = disabled;
  if (applyAllBtn) applyAllBtn.disabled = disabled;
  document.querySelectorAll(".apply-now-btn").forEach((b) => {
    b.disabled = disabled || b.dataset.applied === "true";
  });
}

function updateRunnerStatus(runner) {
  const pill = document.getElementById("runnerStatus");
  const searchBtn = document.getElementById("startSearchBtn");
  const refreshBtn = document.getElementById("refreshSearchBtn");
  const stopBtn = document.getElementById("stopSearchBtn");
  isApplying = Boolean(runner.applying);
  currentApplyingJobId = runner.current_job_id || null;

  const actCard = document.getElementById("agentActivityCard");
  if (actCard) actCard.classList.toggle("active", Boolean(runner.searching || runner.applying));

  if (runner.searching) {
    pill.textContent = "Searching & Matching…";
    pill.classList.add("active");
    searchBtn.disabled = true;
    if (refreshBtn) refreshBtn.disabled = true;
    if (stopBtn) {
      stopBtn.disabled = false;
      stopBtn.textContent = "🛑 STOP";
    }
  } else if (runner.applying) {
    pill.textContent = "Applying Automatically…";
    pill.classList.add("active");
    if (stopBtn) stopBtn.disabled = true;
    setAllApplyButtonsDisabled(true);
  } else {
    pill.textContent = "Idle";
    pill.classList.remove("active");
    searchBtn.disabled = false;
    if (refreshBtn) refreshBtn.disabled = false;
    if (stopBtn) {
      stopBtn.disabled = true;
      stopBtn.textContent = "🛑 STOP";
    }
    setAllApplyButtonsDisabled(false);
  }
}

function showRoadblock(rb) {
  document.getElementById("roadblockJob").textContent = rb.job_title || "Browser Action";
  document.getElementById("roadblockReason").textContent = rb.reason || "";
  document.getElementById("roadblockUrl").textContent = rb.url || "";
  const autoBtn = document.getElementById("rbAutofillBtn");
  autoBtn.style.display = rb.has_saved_credential ? "inline-flex" : "none";
  if (rb.saved_site_name) {
    autoBtn.textContent = `Auto-fill Saved Login (${rb.saved_site_name})`;
  }
  const ssoSpan = document.getElementById("rbSsoButtons");
  const providers = rb.available_sso_providers || [];
  ssoSpan.innerHTML = providers
    .map(
      (p) =>
        `<button class="btn btn-secondary" onclick="autofillBrowser('${escapeJs(p)}')">🔑 Sign in with ${escapeHtml(
          p.charAt(0).toUpperCase() + p.slice(1)
        )}</button>`
    )
    .join("");
  document.getElementById("roadblockBanner").classList.add("visible");
}

function hideRoadblock() {
  document.getElementById("roadblockBanner").classList.remove("visible");
}

async function fillFormNow() {
  const btn = document.getElementById("rbFillNowBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Filling Form…";
  }
  try {
    const res = await api("/api/browser/fill-now", { method: "POST" });
    alert(`📝 ${res.message}`);
  } catch (e) {
    alert("Fill Form error: " + e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "📝 Fill Form & Upload CV Now";
    }
  }
}

async function resolveRoadblock(decision) {
  await api("/api/browser/roadblock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
}

// --- Interactive Browser ---
async function showBrowser() {
  try {
    await api("/api/browser/show", { method: "POST" });
  } catch (e) {
    alert("Browser error: " + e.message);
  }
}

async function hideBrowser() {
  try {
    await api("/api/browser/hide", { method: "POST" });
  } catch (e) {
    alert("Browser error: " + e.message);
  }
}

async function openBrowser(url) {
  try {
    await api("/api/browser/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
  } catch (e) {
    alert("Browser error: " + e.message);
  }
}

function openCustomUrl() {
  const url = prompt("Enter URL to open in the interactive browser (e.g. https://company.gupy.io):");
  if (url) openBrowser(url);
}

async function autofillBrowser(provider = "") {
  try {
    const res = await api("/api/browser/autofill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });
    if (!res.filled) alert(res.message);
  } catch (e) {
    alert("Autofill error: " + e.message);
  }
}

function toggleSeniorityMenu(ev) {
  ev.stopPropagation();
  const dd = document.getElementById("seniorityDropdown");
  if (dd) dd.classList.toggle("open");
}

document.addEventListener("click", (ev) => {
  const dd = document.getElementById("seniorityDropdown");
  if (dd && !dd.contains(ev.target)) dd.classList.remove("open");
});

function onSeniorityChange(changedEl) {
  const allBoxes = Array.from(document.querySelectorAll('input[name="prefSeniorityOpt"]'));
  if (changedEl && changedEl.value === "Any Seniority" && changedEl.checked) {
    allBoxes.forEach((cb) => {
      if (cb !== changedEl) cb.checked = false;
    });
  } else if (changedEl && changedEl.value !== "Any Seniority" && changedEl.checked) {
    const anyBox = allBoxes.find((cb) => cb.value === "Any Seniority");
    if (anyBox) anyBox.checked = false;
  }
  updateSeniorityDisplay();
  scheduleAutoSaveAll();
}

function getSelectedSeniorities() {
  return Array.from(document.querySelectorAll('input[name="prefSeniorityOpt"]:checked')).map((el) => el.value);
}

function updateSeniorityDisplay() {
  const selected = getSelectedSeniorities();
  const disp = document.getElementById("seniorityDisplay");
  if (disp) disp.textContent = selected.length ? selected.join(", ") : "Any Seniority";
}

function setSelectedSeniorities(valueStr) {
  const raw = String(valueStr || "").trim().toLowerCase();
  const isAny = !raw || raw === "any" || raw === "any seniority";
  const chosen = new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  );
  document.querySelectorAll('input[name="prefSeniorityOpt"]').forEach((cb) => {
    if (isAny) {
      cb.checked = cb.value === "Any Seniority";
    } else {
      cb.checked = chosen.has(cb.value.toLowerCase());
    }
  });
  updateSeniorityDisplay();
}

function collectSearchOptions() {
  const checked = (id, def = true) => {
    const el = document.getElementById(id);
    return el ? el.checked : def;
  };
  return {
    srcLinkedin: checked("srcLinkedin", true),
    srcIndeed: checked("srcIndeed", true),
    srcGlassdoor: checked("srcGlassdoor", true),
    srcZipRecruiter: checked("srcZipRecruiter", true),
    srcRemotive: checked("srcRemotive", true),
    modeHybrid: checked("modeHybrid", true),
    modeRemote: checked("modeRemote", true),
    easyOnly: checked("easyOnly", false),
    includeSkillsInSearch: checked("includeSkillsInSearch", false),
    autoSubmitToggle: checked("autoSubmitToggle", false),
    maxPerQuery: parseInt(document.getElementById("maxPerQuery")?.value || "10", 10) || 10,
  };
}

function populateSearchOptions(opts) {
  if (!opts || typeof opts !== "object") return;
  [
    "srcLinkedin",
    "srcIndeed",
    "srcGlassdoor",
    "srcZipRecruiter",
    "srcRemotive",
    "modeHybrid",
    "modeRemote",
    "easyOnly",
    "includeSkillsInSearch",
    "autoSubmitToggle",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el && typeof opts[id] === "boolean") el.checked = opts[id];
  });
  if (opts.maxPerQuery !== undefined && document.getElementById("maxPerQuery")) {
    document.getElementById("maxPerQuery").value = opts.maxPerQuery;
  }
}

function collectMatchPreferences() {
  const selectedSeniorities = getSelectedSeniorities();
  return {
    search_keywords: document.getElementById("searchKeywords")?.value ?? "",
    search_locations: document.getElementById("searchLocations")?.value ?? "",
    skills: document.getElementById("prefSkills")?.value ?? "",
    industries: document.getElementById("prefIndustries")?.value ?? "",
    seniority: selectedSeniorities.length ? selectedSeniorities.join(", ") : "Any Seniority",
    culture_values: document.getElementById("prefCulture")?.value ?? "",
    personal_positioning: document.getElementById("prefPositioning")?.value ?? "",
    dealbreakers: document.getElementById("prefDealbreakers")?.value ?? "",
    search_options: collectSearchOptions(),
  };
}

function populateMatchPreferences(mp) {
  if (!mp) return;
  if (mp.search_keywords !== undefined && document.getElementById("searchKeywords")) {
    document.getElementById("searchKeywords").value = mp.search_keywords;
  }
  if (mp.search_locations !== undefined && document.getElementById("searchLocations")) {
    document.getElementById("searchLocations").value = mp.search_locations;
  }
  if (mp.skills !== undefined && document.getElementById("prefSkills")) {
    document.getElementById("prefSkills").value = mp.skills;
  }
  if (mp.industries !== undefined && document.getElementById("prefIndustries")) {
    document.getElementById("prefIndustries").value = mp.industries;
  }
  setSelectedSeniorities(mp.seniority || "Manager / Head");
  if (mp.culture_values !== undefined && document.getElementById("prefCulture")) {
    document.getElementById("prefCulture").value = mp.culture_values;
  }
  if (mp.personal_positioning !== undefined && document.getElementById("prefPositioning")) {
    document.getElementById("prefPositioning").value = mp.personal_positioning;
  }
  if (mp.dealbreakers !== undefined && document.getElementById("prefDealbreakers")) {
    document.getElementById("prefDealbreakers").value = mp.dealbreakers;
  }
  if (mp.search_options) {
    populateSearchOptions(mp.search_options);
  }
}

let autoSaveTimer = null;
let profileLoaded = false;

function scheduleAutoSaveAll() {
  if (!profileLoaded || profileBusy) return;
  if (autoSaveTimer) clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(async () => {
    if (profileBusy) return;
    try {
      const activeLang = (profileCache.preferred_language || "pt").toLowerCase();
      const loc = captureCurrentLocalizedEdits();
      const bucket = loc[activeLang] || { summary: "", work_history: "", t_letter_examples: "" };
      const updated = {
        ...profileCache,
        full_name: document.getElementById("profName")?.value ?? profileCache.full_name ?? "",
        email: document.getElementById("profEmail")?.value ?? profileCache.email ?? "",
        phone: document.getElementById("profPhone")?.value ?? profileCache.phone ?? "",
        linkedin_url: document.getElementById("profLinkedin")?.value ?? profileCache.linkedin_url ?? "",
        city: document.getElementById("profCity")?.value ?? profileCache.city ?? "",
        salary_currency: document.getElementById("profSalaryCurrency")?.value ?? profileCache.salary_currency ?? "BRL",
        salary_period: document.getElementById("profSalaryPeriod")?.value ?? profileCache.salary_period ?? "monthly",
        salary_min: parseInt(document.getElementById("profSalaryMin")?.value || "0", 10) || 0,
        salary_max: parseInt(document.getElementById("profSalaryMax")?.value || "0", 10) || 0,
        preferred_language: activeLang,
        edited_language: activeLang,
        localized: loc,
        summary: bucket.summary,
        work_history: bucket.work_history,
        t_letter_examples: bucket.t_letter_examples,
        match_preferences: collectMatchPreferences(),
        silent: true,
      };
      profileCache = await api("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      });
    } catch {}
  }, 700);
}

function bindAutoSaveListeners() {
  const autoSaveIds = [
    "searchKeywords",
    "searchLocations",
    "prefSkills",
    "prefIndustries",
    "prefCulture",
    "prefPositioning",
    "prefDealbreakers",
    "maxPerQuery",
    "srcLinkedin",
    "srcIndeed",
    "srcGlassdoor",
    "srcZipRecruiter",
    "srcRemotive",
    "modeHybrid",
    "modeRemote",
    "easyOnly",
    "includeSkillsInSearch",
    "autoSubmitToggle",
    "profName",
    "profEmail",
    "profPhone",
    "profLinkedin",
    "profCity",
    "profSalaryCurrency",
    "profSalaryPeriod",
    "profSalaryMin",
    "profSalaryMax",
    "profSummary",
    "profHistory",
    "profTLetters",
  ];
  autoSaveIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", scheduleAutoSaveAll);
    el.addEventListener("change", scheduleAutoSaveAll);
  });
}

async function saveMatchPreferences() {
  const updated = {
    ...profileCache,
    match_preferences: collectMatchPreferences(),
  };
  profileCache = await api("/api/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updated),
  });
  alert("Human Fit, Skills & Culture preferences saved!");
}

async function reanalyzeJobs() {
  try {
    const res = await api("/api/jobs/reanalyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectMatchPreferences()),
    });
    if (res.count === 0 || res.reanalyzed === 0) {
      alert("No pending ('new') jobs to re-score.");
    }
  } catch (e) {
    alert(e.message);
  }
}

// --- Search & Jobs ---
async function stopSearch() {
  const stopBtn = document.getElementById("stopSearchBtn");
  if (stopBtn) {
    stopBtn.disabled = true;
    stopBtn.textContent = "⏳ Stopping…";
  }
  try {
    await api("/api/search/stop", { method: "POST" });
  } catch (e) {
    alert(e.message);
  }
}

async function refreshSearch() {
  if (!confirm("Delete all previous job listings and start a clean search?\n\nYour Profile, CVs, Credentials, and Settings will NOT be affected.")) {
    return;
  }
  try {
    await api("/api/stats/clear", { method: "POST" });
    await Promise.all([loadJobs(), loadStats()]);
    await startSearch();
  } catch (e) {
    alert(e.message);
  }
}

async function startSearch() {
  const sources = [];
  if (document.getElementById("srcLinkedin")?.checked) sources.push("linkedin");
  if (document.getElementById("srcIndeed")?.checked) sources.push("indeed");
  if (document.getElementById("srcGlassdoor")?.checked) sources.push("glassdoor");
  if (document.getElementById("srcZipRecruiter")?.checked) sources.push("ziprecruiter");
  if (document.getElementById("srcRemotive")?.checked) sources.push("remotive");
  if (!sources.length) return alert("Select at least one job search platform.");
  const work_modes = [];
  if (document.getElementById("modeHybrid").checked) work_modes.push("hybrid");
  if (document.getElementById("modeRemote").checked) work_modes.push("remote");

  const keywords = document.getElementById("searchKeywords").value.split(",").map((s) => s.trim()).filter(Boolean);
  const locations = document.getElementById("searchLocations").value.split(";").map((s) => s.trim()).filter(Boolean);

  try {
    await api("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sources,
        keywords,
        locations,
        work_modes,
        easy_apply_only: document.getElementById("easyOnly").checked,
        max_per_query: parseInt(document.getElementById("maxPerQuery").value || "10", 10),
        max_total_results: 50,
        include_skills_in_search: document.getElementById("includeSkillsInSearch")?.checked || false,
        match_preferences: collectMatchPreferences(),
      }),
    });
  } catch (e) {
    alert(e.message);
  }
}

async function loadJobs() {
  const status = document.getElementById("filterStatus").value;
  const minScore = parseInt(document.getElementById("filterMinScore").value || "0", 10);
  const salaryFit = document.getElementById("filterSalaryFit")?.value || "all";
  jobsCache = await api(
    `/api/jobs?status=${encodeURIComponent(status)}&min_score=${minScore}&salary_fit=${encodeURIComponent(salaryFit)}`
  );
  renderJobs();
}

function formatSalary(avg, currency, period) {
  if (!avg || avg <= 0) return "";
  const sym = currency === "USD" ? "$" : currency === "EUR" ? "€" : "R$";
  const suffix = period === "yearly" ? "/yr" : "/mo";
  const val = avg >= 1000 ? `${(avg / 1000).toFixed(avg % 1000 === 0 ? 0 : 1)}k` : String(avg);
  return `${sym} ${val}${suffix}`;
}

function salaryBadgeHtml(j) {
  const est = formatSalary(j.estimated_salary_avg, j.estimated_salary_currency, j.estimated_salary_period);
  const fit = j.salary_fit || "unknown";
  if (fit === "in_range") {
    return `<span class="badge badge-salary-in" title="${escapeHtml(j.salary_note || "")}">💰 In Range (${est})</span>`;
  }
  if (fit === "above_range") {
    return `<span class="badge badge-salary-above" title="${escapeHtml(j.salary_note || "")}">💰 Above Range (${est})</span>`;
  }
  if (fit === "below_range") {
    return `<span class="badge badge-salary-below" title="${escapeHtml(j.salary_note || "")}">⚠️ Below Range (${est})</span>`;
  }
  if (est) {
    return `<span class="badge" title="${escapeHtml(j.salary_note || "")}">💰 Est. ${est}</span>`;
  }
  return "";
}

function renderJobs() {
  const container = document.getElementById("jobsList");
  const selectedCount = jobsCache.filter((j) => j.selected === 1).length;
  const applicableCount = jobsCache.filter((j) => ["new", "needs_action", "failed"].includes(j.status)).length;
  document.getElementById("selectedCount").textContent = selectedCount;
  const appAllEl = document.getElementById("applicableCount");
  if (appAllEl) appAllEl.textContent = applicableCount;

  if (!jobsCache.length) {
    container.innerHTML = `<div class="card" style="color:var(--muted); text-align:center;">No jobs indexed yet. Click <strong>Search &amp; Score Jobs</strong> above or <strong>+ Add Job URL</strong>.</div>`;
    return;
  }

  container.innerHTML = jobsCache
    .map((j) => {
      const scoreClass = j.match_score >= 75 ? "badge-score-high" : j.match_score >= 50 ? "badge-score-mid" : "badge-score-low";
      const tierLabel = TIER_LABELS[j.priority_tier] || `P${j.priority_tier}`;
      const tierClass = j.priority_tier === 1 ? "badge-tier-1" : "";
      const statusClass = j.status === "applied" ? "badge-status-applied" : "";
      const sourceTag =
        j.source === "linkedin"
          ? "LinkedIn"
          : j.source === "indeed"
          ? "Indeed"
          : j.source === "glassdoor"
          ? "Glassdoor"
          : j.source === "ziprecruiter"
          ? "ZipRecruiter"
          : j.source === "remotive"
          ? "Remotive"
          : j.source === "gupy"
          ? "Gupy"
          : "External";
      const applyLabel =
        j.apply_type === "easy_apply"
          ? "LinkedIn Easy Apply"
          : j.source === "indeed"
          ? "Indeed"
          : j.source === "glassdoor"
          ? "Glassdoor"
          : j.source === "ziprecruiter"
          ? "ZipRecruiter"
          : j.source === "remotive"
          ? "Remotive (Intl Remote)"
          : "External ATS";

      return `
      <div class="job-card ${j.selected ? "selected" : ""}">
        <div class="job-header">
          <div style="display:flex; gap:10px; align-items:flex-start;">
            <input type="checkbox" ${j.selected ? "checked" : ""} onchange="toggleSelect(${j.id}, this.checked)" style="margin-top:4px; width:16px; height:16px;" />
            <div>
              <div class="job-title">${escapeHtml(j.title)} <span style="font-weight:600; font-size:0.86rem; color:#93c5fd;">(${escapeHtml(sourceTag)})</span></div>
              <div class="job-meta">${escapeHtml(j.company)} • ${escapeHtml(j.location)} • ${escapeHtml(j.work_mode)}</div>
              <div class="badges">
                <span class="badge ${scoreClass}">Match: ${j.match_score}%</span>
                <span class="badge ${tierClass}">${tierLabel}</span>
                ${salaryBadgeHtml(j)}
                <span class="badge badge-lang">Lang: ${(j.language || "pt").toUpperCase()}</span>
                <span class="badge">${applyLabel}</span>
                <span class="badge ${statusClass}">Status: ${j.status}</span>
              </div>
            </div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="deleteJob(${j.id})" title="Remove">✕</button>
        </div>
        ${j.match_reason ? `<div class="job-reason">${escapeHtml(j.match_reason)}</div>` : ""}
        ${j.missing_skills ? `<div class="job-meta" style="margin-top:4px;">Gaps: ${escapeHtml(j.missing_skills)}</div>` : ""}
        ${j.status_note ? `<div class="job-meta" style="margin-top:4px; color:#fde68a;">Note: ${escapeHtml(j.status_note)}</div>` : ""}
        <div class="job-actions">
          <button class="btn btn-secondary btn-sm" onclick="viewMaterials(${j.id})">📝 T-Letter &amp; Cover Letter (${(j.language || "pt").toUpperCase()})</button>
          <button class="btn btn-secondary btn-sm" onclick="openBrowser('${escapeJs(j.url)}')">🌐 Open in Browser</button>
          <button
            class="btn btn-success btn-sm apply-now-btn"
            data-applied="${j.status === "applied" ? "true" : "false"}"
            ${isApplying || j.status === "applying" || j.status === "applied" ? "disabled" : ""}
            onclick="applySingle(${j.id})"
          >${j.status === "applied" ? "✅ Applied" : currentApplyingJobId === j.id || j.status === "applying" ? "⏳ Applying…" : "▶ Apply Now"}</button>
        </div>
      </div>`;
    })
    .join("");
}

async function toggleSelect(jobId, selected) {
  await api(`/api/jobs/${jobId}/select?selected=${selected}`, { method: "PATCH" });
  const item = jobsCache.find((j) => j.id === jobId);
  if (item) item.selected = selected ? 1 : 0;
  renderJobs();
}

async function selectStrongMatches() {
  for (const j of jobsCache) {
    if (j.match_score >= 75 && j.status === "new" && !j.selected) {
      await api(`/api/jobs/${j.id}/select?selected=true`, { method: "PATCH" });
    }
  }
  loadJobs();
}

async function applySelected() {
  if (isApplying) return;
  const auto_submit = document.getElementById("autoSubmitToggle").checked;
  isApplying = true;
  setAllApplyButtonsDisabled(true);
  try {
    await api("/api/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_submit }),
    });
  } catch (e) {
    isApplying = false;
    setAllApplyButtonsDisabled(false);
    alert(e.message);
  }
}

async function applyAll() {
  if (isApplying) return;
  const applicable = jobsCache.filter((j) => ["new", "needs_action", "failed"].includes(j.status));
  if (!applicable.length) {
    return alert("No pending jobs in the current filtered list to apply for.");
  }
  if (!confirm(`Start automated applications for all ${applicable.length} pending job(s) in the current list?`)) {
    return;
  }
  const auto_submit = document.getElementById("autoSubmitToggle").checked;
  isApplying = true;
  setAllApplyButtonsDisabled(true);
  try {
    await api("/api/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_ids: applicable.map((j) => j.id), auto_submit }),
    });
  } catch (e) {
    isApplying = false;
    setAllApplyButtonsDisabled(false);
    alert(e.message);
  }
}

async function applySingle(jobId) {
  if (isApplying) return;
  const auto_submit = document.getElementById("autoSubmitToggle").checked;
  isApplying = true;
  currentApplyingJobId = jobId;
  setAllApplyButtonsDisabled(true);
  try {
    await api("/api/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_ids: [jobId], auto_submit }),
    });
  } catch (e) {
    isApplying = false;
    currentApplyingJobId = null;
    setAllApplyButtonsDisabled(false);
    alert(e.message);
  }
}

let activeLetterJobId = null;

function updateCoverCharCount() {
  const ta = document.getElementById("modalCoverLetter");
  const counter = document.getElementById("coverCharCount");
  if (!ta || !counter) return;
  const len = (ta.value || "").length;
  counter.textContent = `${len} / 850 chars`;
  counter.style.color = len > 850 ? "var(--danger)" : "var(--muted)";
}

function viewMaterials(jobId) {
  activeLetterJobId = jobId;
  const job = jobsCache.find((j) => j.id === jobId);
  document.getElementById("letterModalTitle").textContent = `Materials (${(job?.language || "pt").toUpperCase()}) — ${job?.title || ""}`;
  document.getElementById("modalTLetter").value = job?.generated_t_letter || "";
  document.getElementById("modalCoverLetter").value = job?.generated_cover_letter || "";
  updateCoverCharCount();
  document.getElementById("letterModal").classList.add("open");
}

async function generateModalLetter(letterType) {
  if (!activeLetterJobId) return;
  const isT = letterType === "t_letter";
  const btn = document.getElementById(isT ? "genTLetterBtn" : "genCoverLetterBtn");
  const spinner = document.getElementById(isT ? "spinnerTLetter" : "spinnerCoverLetter");
  const targetTa = document.getElementById(isT ? "modalTLetter" : "modalCoverLetter");

  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.add("active");
  try {
    const res = await api(`/api/jobs/${activeLetterJobId}/materials`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ letter_type: letterType, regenerate: true }),
    });
    const text = isT ? res.t_letter : res.cover_letter;
    if (targetTa) targetTa.value = text || "";
    const job = jobsCache.find((j) => j.id === activeLetterJobId);
    if (job) {
      if (isT) job.generated_t_letter = text || "";
      else job.generated_cover_letter = text || "";
    }
    updateCoverCharCount();
  } catch (e) {
    alert("GenAI letter error: " + e.message);
  } finally {
    if (btn) btn.disabled = false;
    if (spinner) spinner.classList.remove("active");
  }
}

async function deleteJob(jobId) {
  await api(`/api/jobs/${jobId}`, { method: "DELETE" });
  loadJobs();
}

function openManualJobModal() {
  document.getElementById("manualJobModal").classList.add("open");
}

async function submitManualJob() {
  try {
    await api("/api/jobs/manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: document.getElementById("mjTitle").value,
        company: document.getElementById("mjCompany").value,
        location: document.getElementById("mjLocation").value,
        url: document.getElementById("mjUrl").value,
        description: document.getElementById("mjDesc").value,
      }),
    });
    closeModal("manualJobModal");
    loadJobs();
  } catch (e) {
    alert(e.message);
  }
}

// --- Analytics Dashboard ---
async function loadStats() {
  const stats = await api("/api/stats");
  renderStats(stats);
}

async function clearStats() {
  if (
    !confirm(
      "Reset all dashboard statistics and clear indexed jobs?\n\nYour Profile, CVs, Credentials, and Settings will NOT be affected."
    )
  ) {
    return;
  }
  await api("/api/stats/clear", { method: "POST" });
  await Promise.all([loadStats(), loadJobs()]);
}

function renderBars(containerId, items, totalOverride = 0) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = `<div style="color:var(--muted); font-size:0.84rem;">No data yet.</div>`;
    return;
  }
  const maxVal = totalOverride || Math.max(...items.map((i) => i.total), 1);
  el.innerHTML = items
    .map((item) => {
      const pct = Math.round((item.total / maxVal) * 100);
      return `
      <div class="bar-row">
        <div class="bar-header">
          <span>${escapeHtml(item.label)}</span>
          <span style="color:var(--muted);">${item.total} total • <strong style="color:#86efac;">${item.applied} applied</strong> • avg ${item.avg_score}%</span>
        </div>
        <div class="bar-track"><div class="bar-fill ${item.applied > 0 ? "success" : ""}" style="width:${pct}%;"></div></div>
      </div>`;
    })
    .join("");
}

function renderStats(stats) {
  const s = stats.summary || {};
  document.getElementById("kpiGrid").innerHTML = `
    <div class="kpi-card"><div class="kpi-label">Indexed Jobs</div><div class="kpi-value">${s.total_jobs || 0}</div><div class="kpi-sub">${s.new_count || 0} pending review</div></div>
    <div class="kpi-card"><div class="kpi-label">Jobs Applied</div><div class="kpi-value" style="color:#86efac;">${s.applied_count || 0}</div><div class="kpi-sub">${s.apply_rate_pct || 0}% apply rate</div></div>
    <div class="kpi-card"><div class="kpi-label">Avg Match Score</div><div class="kpi-value">${s.avg_match_score || 0}%</div><div class="kpi-sub">Applied avg: ${s.avg_applied_match_score || 0}%</div></div>
    <div class="kpi-card"><div class="kpi-label">Strong Matches</div><div class="kpi-value" style="color:#93c5fd;">${s.strong_matches || 0}</div><div class="kpi-sub">Score ≥ 75%</div></div>
    <div class="kpi-card"><div class="kpi-label">Salary In/Above Range</div><div class="kpi-value" style="color:#86efac;">${s.in_range_salary || 0}</div><div class="kpi-sub">${s.below_range_salary || 0} below range</div></div>
    <div class="kpi-card"><div class="kpi-label">Needs Action / Failed</div><div class="kpi-value" style="color:#fde68a;">${(s.needs_action_count || 0) + (s.failed_count || 0)}</div><div class="kpi-sub">${s.skipped_count || 0} skipped</div></div>
  `;

  renderBars("chartPlatform", stats.by_platform);
  renderBars("chartStatus", stats.by_status);
  renderBars("chartSalary", stats.by_salary_fit);
  renderBars("chartPriority", stats.by_priority);
  renderBars("chartLanguage", stats.by_language);
  renderBars("chartPositions", stats.top_positions);
  renderBars("chartCompanies", stats.top_companies);

  const recent = stats.recent_applications || [];
  const tbl = document.getElementById("recentAppsTable");
  if (!recent.length) {
    tbl.innerHTML = `<div style="color:var(--muted); font-size:0.85rem;">No jobs tracked yet. Run a search from the Jobs tab to populate analytics.</div>`;
    return;
  }
  tbl.innerHTML = `
    <table class="simple-table">
      <thead>
        <tr><th>Position</th><th>Company</th><th>Platform</th><th>Lang</th><th>Match</th><th>Est. Salary</th><th>Status</th></tr>
      </thead>
      <tbody>
        ${recent
          .map(
            (r) => `<tr>
            <td><a href="${escapeHtml(r.url)}" target="_blank" style="color:#93c5fd; text-decoration:none;">${escapeHtml(r.title)}</a></td>
            <td>${escapeHtml(r.company)}</td>
            <td>${escapeHtml(r.platform)}</td>
            <td>${escapeHtml(r.language)}</td>
            <td><strong>${r.match_score}%</strong></td>
            <td>${salaryBadgeHtml(r) || "<span style='color:var(--muted);'>—</span>"}</td>
            <td><span class="badge ${r.status === "applied" ? "badge-status-applied" : ""}">${escapeHtml(r.status)}</span></td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

function updateLangToggleUI(lang) {
  const active = (lang || "pt").toLowerCase();
  const ptBtn = document.getElementById("langBtnPt");
  const enBtn = document.getElementById("langBtnEn");
  if (ptBtn) ptBtn.classList.toggle("active", active === "pt");
  if (enBtn) enBtn.classList.toggle("active", active === "en");
  const uploadSel = document.getElementById("docLang");
  if (uploadSel && (active === "pt" || active === "en")) {
    uploadSel.value = active;
  }
}

function syncLocalizedFieldsToUI(lang) {
  const code = (lang || "pt").toLowerCase();
  const loc = (profileCache.localized && profileCache.localized[code]) || {};
  document.getElementById("profSummary").value = loc.summary || "";
  document.getElementById("profHistory").value = loc.work_history || "";
  document.getElementById("profTLetters").value = loc.t_letter_examples || "";
}

function captureCurrentLocalizedEdits() {
  const currentLang = (profileCache.preferred_language || "pt").toLowerCase();
  const loc = { ...(profileCache.localized || {}) };
  loc[currentLang] = {
    summary: document.getElementById("profSummary")?.value || "",
    work_history: document.getElementById("profHistory")?.value || "",
    t_letter_examples: document.getElementById("profTLetters")?.value || "",
  };
  return loc;
}

let profileBusy = false;

function setProfileControlsDisabled(disabled) {
  ["langBtnEn", "langBtnPt", "processProfileBtn"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
  });
}

async function setPreferredLanguage(lang) {
  if (profileBusy) return;
  const newLang = (lang || "pt").toLowerCase();
  const prevLang = (profileCache.preferred_language || "pt").toLowerCase();
  if (newLang === prevLang) {
    updateLangToggleUI(newLang);
    syncLocalizedFieldsToUI(newLang);
    return;
  }
  profileBusy = true;
  setProfileControlsDisabled(true);
  try {
    const loc = captureCurrentLocalizedEdits();
    const targetBucket = loc[newLang] || { summary: "", work_history: "", t_letter_examples: "" };
    const updated = {
      ...profileCache,
      preferred_language: newLang,
      edited_language: prevLang,
      localized: loc,
      summary: targetBucket.summary,
      work_history: targetBucket.work_history,
      t_letter_examples: targetBucket.t_letter_examples,
    };
    profileCache = await api("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    });
    updateLangToggleUI(newLang);
    syncLocalizedFieldsToUI(newLang);
    await Promise.all([loadDocuments(), loadJobs()]);
  } finally {
    profileBusy = false;
    setProfileControlsDisabled(false);
  }
}

async function processProfileFromDocs() {
  if (profileBusy) return;
  const lang = (profileCache.preferred_language || "pt").toLowerCase();
  const btn = document.getElementById("processProfileBtn");
  profileBusy = true;
  setProfileControlsDisabled(true);
  if (btn) btn.textContent = `⏳ Processing (${lang.toUpperCase()})…`;
  try {
    const updated = await api("/api/profile/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: lang }),
    });
    profileCache = updated;
    updateLangToggleUI(lang);
    syncLocalizedFieldsToUI(lang);
    alert(`Profile extracted in ${lang === "en" ? "English (EN)" : "Brazilian Portuguese (PT)"} without altering the other language! You can edit any section and click Save Profile.`);
  } catch (e) {
    alert("Process error: " + e.message);
  } finally {
    profileBusy = false;
    setProfileControlsDisabled(false);
    if (btn) btn.textContent = "⚙️ Process";
  }
}

// --- Profile & Documents ---
async function loadProfile() {
  profileCache = await api("/api/profile");
  const activeLang = (profileCache.preferred_language || "pt").toLowerCase();
  updateLangToggleUI(activeLang);
  document.getElementById("profName").value = profileCache.full_name || "";
  document.getElementById("profEmail").value = profileCache.email || "";
  document.getElementById("profPhone").value = profileCache.phone || "";
  document.getElementById("profLinkedin").value = profileCache.linkedin_url || "";
  document.getElementById("profCity").value = profileCache.city || "";
  document.getElementById("profSalaryCurrency").value = profileCache.salary_currency || "BRL";
  document.getElementById("profSalaryPeriod").value = profileCache.salary_period || "monthly";
  document.getElementById("profSalaryMin").value = profileCache.salary_min || "";
  document.getElementById("profSalaryMax").value = profileCache.salary_max || "";
  syncLocalizedFieldsToUI(activeLang);
  populateMatchPreferences(profileCache.match_preferences || {});
  profileLoaded = true;
}

async function saveProfile() {
  const activeLang = (profileCache.preferred_language || "pt").toLowerCase();
  const loc = captureCurrentLocalizedEdits();
  const bucket = loc[activeLang];
  const updated = {
    ...profileCache,
    full_name: document.getElementById("profName").value,
    email: document.getElementById("profEmail").value,
    phone: document.getElementById("profPhone").value,
    linkedin_url: document.getElementById("profLinkedin").value,
    city: document.getElementById("profCity").value,
    salary_currency: document.getElementById("profSalaryCurrency").value,
    salary_period: document.getElementById("profSalaryPeriod").value,
    salary_min: parseInt(document.getElementById("profSalaryMin").value || "0", 10) || 0,
    salary_max: parseInt(document.getElementById("profSalaryMax").value || "0", 10) || 0,
    preferred_language: activeLang,
    edited_language: activeLang,
    localized: loc,
    summary: bucket.summary,
    work_history: bucket.work_history,
    t_letter_examples: bucket.t_letter_examples,
  };
  profileCache = await api("/api/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updated),
  });
  await loadJobs();
  alert(`Profile (${activeLang.toUpperCase()}) & salary range saved without altering the other language!`);
}

async function loadDocuments() {
  const docs = await api("/api/documents");
  const el = document.getElementById("documentsList");
  if (!docs.length) {
    el.innerHTML = `<div style="color:var(--muted); font-size:0.85rem;">No files uploaded yet. Upload your PT, EN, and IT resumes above.</div>`;
    return;
  }
  el.innerHTML = `
    <table class="simple-table">
      <thead><tr><th>File</th><th>Type</th><th>Language</th><th>Reference Priority</th><th>Extracted Text</th><th></th></tr></thead>
      <tbody>
        ${docs
          .map((d) => {
            const prio = (d.priority || "primary").toLowerCase();
            const isPrimary = prio === "primary";
            return `<tr class="${isPrimary ? "doc-primary-row" : ""}">
            <td>${escapeHtml(d.filename)}</td>
            <td>${escapeHtml(d.doc_type)}</td>
            <td><span class="badge badge-lang">${d.language.toUpperCase()}</span></td>
            <td>
              <select onchange="updateDocPriority(${d.id}, this.value)" style="width:130px; padding:4px 8px; font-size:0.82rem;">
                <option value="primary" ${isPrimary ? "selected" : ""}>Primary</option>
                <option value="secondary" ${!isPrimary ? "selected" : ""}>Secondary</option>
              </select>
            </td>
            <td>${d.text_length.toLocaleString()} chars</td>
            <td><button class="btn btn-danger btn-sm" onclick="deleteDoc(${d.id})">Delete</button></td>
          </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;
}

async function updateDocPriority(docId, priority) {
  await api(`/api/documents/${docId}/priority`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ priority }),
  });
  loadDocuments();
}

async function uploadDocument() {
  const fileInput = document.getElementById("docFile");
  if (!fileInput.files.length) return alert("Choose a PDF, DOCX, or TXT file first.");
  const btn = document.getElementById("uploadDocBtn");
  if (btn) btn.disabled = true;
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("doc_type", document.getElementById("docType").value);
  fd.append("language", document.getElementById("docLang").value);
  try {
    await api("/api/documents/upload", { method: "POST", body: fd });
    fileInput.value = "";
    loadDocuments();
  } catch (e) {
    alert("Upload failed: " + e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function deleteDoc(id) {
  await api(`/api/documents/${id}`, { method: "DELETE" });
  loadDocuments();
}

// --- CV Analysis Tab ---
let cvAnalysisLang = "pt";
let cvAnalysisCache = { pt: null, en: null };
let cvCountdownTimer = null;
let cvLastProgress = null;

function updateCvLangButtons() {
  const ptBtn = document.getElementById("cvLangBtnPt");
  const enBtn = document.getElementById("cvLangBtnEn");
  if (ptBtn) ptBtn.classList.toggle("active", cvAnalysisLang === "pt");
  if (enBtn) enBtn.classList.toggle("active", cvAnalysisLang === "en");
}

function selectCvAnalysisLang(lang) {
  cvAnalysisLang = (lang || "pt").toLowerCase() === "en" ? "en" : "pt";
  updateCvLangButtons();
  renderCvAnalysis();
}

function setCvRunButtonState(running) {
  const btn = document.getElementById("runCvCheckBtn");
  if (!btn) return;
  btn.disabled = running;
  btn.textContent = running ? `⏳ Analyzing (${cvAnalysisLang.toUpperCase()})…` : "🔍 Run Check";
}

function updateCvAnalysisProgress(p) {
  cvLastProgress = p;
  const box = document.getElementById("cvProgressBox");
  const lbl = document.getElementById("cvProgressLabel");
  const tmr = document.getElementById("cvProgressTimer");
  const fill = document.getElementById("cvProgressFill");
  if (!box) return;

  if (cvCountdownTimer) {
    clearInterval(cvCountdownTimer);
    cvCountdownTimer = null;
  }
  if (!p || !p.active) {
    box.classList.remove("visible");
    setCvRunButtonState(false);
    return;
  }
  box.classList.add("visible");
  setCvRunButtonState(true);
  if (lbl) lbl.textContent = p.stage || "Running CV Analysis…";

  const refreshTimer = () => {
    if (!cvLastProgress || !cvLastProgress.active) return;
    const rem = Math.max(0, Math.ceil((cvLastProgress.deadline_ts || 0) - Date.now() / 1000));
    const mm = String(Math.floor(rem / 60)).padStart(2, "0");
    const ss = String(rem % 60).padStart(2, "0");
    if (tmr) tmr.textContent = `⏱️ ${mm}:${ss} left • ${cvLastProgress.found || 0} peer profiles scanned`;
    const pct = Math.min(95, Math.max(12, Math.round(((180 - rem) / 180) * 100)));
    if (fill) fill.style.width = `${pct}%`;
  };
  refreshTimer();
  cvCountdownTimer = setInterval(refreshTimer, 1000);
}

async function loadCvAnalysis() {
  try {
    const data = await api("/api/cv-analysis");
    cvAnalysisCache.pt = data.pt || null;
    cvAnalysisCache.en = data.en || null;
    setCvRunButtonState(Boolean(data.running));
    updateCvLangButtons();
    renderCvAnalysis();
  } catch {}
}

async function runCvAnalysis() {
  setCvRunButtonState(true);
  // Immediately show the progress bar under the button so user gets instant visual feedback
  updateCvAnalysisProgress({
    active: true,
    stage: `Starting document-only CV Audit & 3-min LinkedIn scan (${cvAnalysisLang.toUpperCase()})…`,
    deadline_ts: Date.now() / 1000 + 180,
    found: 0,
  });
  try {
    await api("/api/cv-analysis/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: cvAnalysisLang }),
    });
  } catch (e) {
    updateCvAnalysisProgress({ active: false });
    setCvRunButtonState(false);
    alert("CV Analysis error: " + e.message);
  }
}

function addTitleToSearchKeywords(title) {
  const el = document.getElementById("searchKeywords");
  if (!el || !title) return;
  const existing = el.value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (!existing.some((k) => k.toLowerCase() === title.toLowerCase())) {
    existing.push(title);
    el.value = existing.join(", ");
    scheduleAutoSaveAll();
    alert(`Added "${title}" to Target Job Titles / Keywords!`);
  } else {
    alert(`"${title}" is already in your Target Job Titles.`);
  }
}

function renderCvAnalysis() {
  const container = document.getElementById("cvAnalysisContent");
  if (!container) return;
  const isPt = cvAnalysisLang === "pt";
  const T = isPt
    ? {
        empty: `Nenhuma análise de CV em <strong>PT (Português)</strong> salva ainda. Clique em <strong>🔍 Run Check</strong> acima para auditar seus documentos enviados em Português Brasileiro.`,
        verdict: "Veredito Executivo da Auditoria (PT)",
        updated: "Atualizado em",
        strengths: "💪 Principais Pontos Fortes",
        skills: "🧠 Competências Principais (Core Skills)",
        areas: "🏢 Áreas de Atuação Mais Adequadas",
        positions: "🎯 Cargos Mais Compatíveis",
        gaps: "⚠️ Lacunas Importantes e Recomendações",
        peers: "🔎 Títulos no LinkedIn de Perfis Similares (Busca de 3 min)",
        addBtn: "+ Adicionar à Busca",
        peerSummary: (n) => `Sintetizado a partir de ${n} perfil(is) similar(es) analisado(s) no LinkedIn.`,
        none: "Nenhum item encontrado.",
      }
    : {
        empty: `No <strong>EN (English)</strong> CV analysis saved yet. Click <strong>🔍 Run Check</strong> above to audit your uploaded documents in English.`,
        verdict: "Executive Audit Verdict (EN)",
        updated: "Updated",
        strengths: "💪 Main Strengths",
        skills: "🧠 Core Skills",
        areas: "🏢 Most Suitable Areas of Work",
        positions: "🎯 Most Compatible Job Positions",
        gaps: "⚠️ Important Gaps & Recommendations",
        peers: "🔎 LinkedIn Peer Titles (3-Min Market Scan)",
        addBtn: "+ Add to Search",
        peerSummary: (n) => `Synthesized from ${n} LinkedIn peer profile(s) with similar backgrounds.`,
        none: "None listed.",
      };

  const data = cvAnalysisCache[cvAnalysisLang];
  if (!data) {
    container.innerHTML = `<div class="card" style="color:var(--muted); text-align:center;">${T.empty}</div>`;
    return;
  }

  const filesHtml = (data.analyzed_files || [])
    .map((f) => `<span class="badge">${escapeHtml(f)}</span>`)
    .join(" ");

  const strengthsHtml = (data.main_strengths || [])
    .map((s) => `<li>${escapeHtml(s)}</li>`)
    .join("");

  const skillsHtml = (data.core_skills || [])
    .map((s) => `<span class="skill-chip">${escapeHtml(s)}</span>`)
    .join("");

  const areasHtml = (data.suitable_areas || [])
    .map(
      (a) => `<div class="cv-item-card">
        <div class="cv-item-header"><strong>${escapeHtml(a.area)}</strong></div>
        <div style="font-size:0.85rem; color:#cbd5e1;">${escapeHtml(a.why)}</div>
      </div>`
    )
    .join("");

  const positionsHtml = (data.compatible_positions || [])
    .map(
      (p) => `<div class="cv-item-card">
        <div class="cv-item-header">
          <div>
            <strong>${escapeHtml(p.title)}</strong>
            <span class="badge badge-score-high" style="margin-left:6px;">${escapeHtml(p.fit_level || (isPt ? "Forte" : "Strong"))}</span>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="addTitleToSearchKeywords('${escapeJs(p.title)}')">${T.addBtn}</button>
        </div>
        <div style="font-size:0.85rem; color:#cbd5e1;">${escapeHtml(p.why)}</div>
      </div>`
    )
    .join("");

  const gapsHtml = (data.important_gaps || [])
    .map((g) => {
      const sev = (g.severity || "Medium").toLowerCase();
      const sevClass =
        sev === "high" || sev === "alta"
          ? "badge-score-low"
          : sev === "low" || sev === "baixa"
          ? "badge-score-high"
          : "badge-score-mid";
      return `<div class="cv-item-card">
        <div class="cv-item-header">
          <strong>${escapeHtml(g.gap)}</strong>
          <span class="badge ${sevClass}">${escapeHtml(g.severity || (isPt ? "Média" : "Medium"))}</span>
        </div>
        <div style="font-size:0.85rem; color:#cbd5e1;">💡 ${escapeHtml(g.recommendation)}</div>
      </div>`;
    })
    .join("");

  const peersHtml = (data.linkedin_peer_titles || [])
    .map(
      (pt) => `<div class="cv-item-card">
        <div class="cv-item-header">
          <strong>${escapeHtml(pt.title)}</strong>
          <button class="btn btn-secondary btn-sm" onclick="addTitleToSearchKeywords('${escapeJs(pt.title)}')">${T.addBtn}</button>
        </div>
        <div style="font-size:0.85rem; color:#cbd5e1;">${escapeHtml(pt.insight)}</div>
      </div>`
    )
    .join("");

  container.innerHTML = `
    <div class="card">
      <div class="row space-between" style="margin-bottom:8px;">
        <h3 style="margin:0;">${T.verdict}</h3>
        <span style="font-size:0.78rem; color:var(--muted);">${T.updated}: ${(data.updated_at || "").slice(0, 19).replace("T", " ")}</span>
      </div>
      <p style="margin:0 0 10px; font-size:0.93rem; color:#f1f5f9;">${escapeHtml(data.executive_verdict)}</p>
      <div class="badges">${filesHtml}</div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>${T.strengths}</h3>
        <ul class="cv-list">${strengthsHtml || `<li>${T.none}</li>`}</ul>
      </div>
      <div class="card">
        <h3>${T.skills}</h3>
        <div class="skill-chips">${skillsHtml || `<span style='color:var(--muted);'>${T.none}</span>`}</div>
      </div>
      <div class="card">
        <h3>${T.areas}</h3>
        ${areasHtml || `<div style='color:var(--muted);'>${T.none}</div>`}
      </div>
      <div class="card">
        <h3>${T.positions}</h3>
        ${positionsHtml || `<div style='color:var(--muted);'>${T.none}</div>`}
      </div>
      <div class="card">
        <h3>${T.gaps}</h3>
        ${gapsHtml || `<div style='color:var(--muted);'>${T.none}</div>`}
      </div>
      <div class="card">
        <h3>${T.peers}</h3>
        ${
          data.peer_scan_note
            ? `<p style="font-size:0.8rem; color:#fde68a; margin-top:0;">${escapeHtml(data.peer_scan_note)}</p>`
            : `<p style="font-size:0.8rem; color:var(--muted); margin-top:0;">${T.peerSummary(data.peer_scan_count || 0)}</p>`
        }
        ${peersHtml || `<div style='color:var(--muted);'>${T.none}</div>`}
      </div>
    </div>
  `;
}

// --- Credentials Vault & SSO Sessions ---
let ssoPollTimer = null;

async function connectSso(provider) {
  try {
    await api("/api/browser/sso/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });
    await Promise.all([loadCredentials(), loadSsoStatus()]);
    // Poll briefly until login cookie is validated in the persistent browser
    if (ssoPollTimer) clearInterval(ssoPollTimer);
    let checks = 0;
    ssoPollTimer = setInterval(async () => {
      checks++;
      const status = await loadSsoStatus();
      if ((status && status[provider]?.validated) || checks >= 40) {
        clearInterval(ssoPollTimer);
        ssoPollTimer = null;
      }
    }, 3000);
  } catch (e) {
    alert("SSO login error: " + e.message);
  }
}

let ssoStatusCache = {};

function renderSsoStatus(status) {
  if (!status) return;
  ssoStatusCache = status;
  for (const [prov, info] of Object.entries(status)) {
    const validated = typeof info === "boolean" ? info : Boolean(info?.validated);
    const revoked = typeof info === "object" && Boolean(info?.revoked);
    const btn = document.getElementById(`ssoBtn-${prov}`);
    const lbl = document.getElementById(`ssoStatus-${prov}`);
    if (lbl) {
      if (validated) {
        lbl.textContent = "✅ Validated";
        lbl.style.color = "#86efac";
        if (btn) {
          btn.disabled = true;
          btn.classList.add("validated");
        }
      } else if (revoked) {
        lbl.textContent = "⚠️ Reconnect →";
        lbl.style.color = "#fde68a";
        if (btn) {
          btn.disabled = false;
          btn.classList.remove("validated");
        }
      } else {
        lbl.textContent = "Sign in →";
        lbl.style.color = "var(--muted)";
        if (btn) {
          btn.disabled = false;
          btn.classList.remove("validated");
        }
      }
    }
    // Sync matching "Test SSO" buttons in the Saved Site & SSO Logins table
    document.querySelectorAll(`.test-sso-btn[data-provider="${prov}"]`).forEach((tb) => {
      tb.classList.remove("btn-test-ok", "btn-test-fail");
      if (validated) {
        tb.classList.add("btn-test-ok");
        tb.textContent = "✅ Test SSO";
      } else if (revoked) {
        tb.classList.add("btn-test-fail");
        tb.textContent = "❌ Test SSO";
      }
    });
  }
}

async function testSavedSso(prov, btnEl) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = "Testing…";
    btnEl.classList.remove("btn-test-ok", "btn-test-fail");
  }
  try {
    // 1. Check live persistent browser cookie validation first
    const status = await loadSsoStatus();
    if (status && status[prov]?.validated) {
      if (btnEl) {
        btnEl.classList.add("btn-test-ok");
        btnEl.textContent = "✅ Test SSO";
      }
      return;
    }
    // 2. Otherwise trigger autofill / SSO check on current browser tab
    const res = await api("/api/browser/autofill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: prov }),
    });
    const afterStatus = await loadSsoStatus();
    const ok = Boolean(res?.filled) || Boolean(afterStatus && afterStatus[prov]?.validated);
    if (btnEl) {
      btnEl.classList.add(ok ? "btn-test-ok" : "btn-test-fail");
      btnEl.textContent = ok ? "✅ Test SSO" : "❌ Test SSO";
    }
  } catch (e) {
    if (btnEl) {
      btnEl.classList.add("btn-test-fail");
      btnEl.textContent = "❌ Test SSO";
    }
  } finally {
    if (btnEl) btnEl.disabled = false;
  }
}

async function loadSsoStatus() {
  try {
    const status = await api("/api/browser/sso/status");
    renderSsoStatus(status);
    return status;
  } catch {
    return null;
  }
}

function prefillSso(name, domain, provider) {
  document.getElementById("credName").value = name;
  document.getElementById("credDomain").value = domain;
  document.getElementById("credProvider").value = provider;
  if (!document.getElementById("credUser").value && profileCache.email) {
    document.getElementById("credUser").value = profileCache.email;
  }
  document.getElementById("credPass").focus();
}

async function loadCredentials() {
  const creds = await api("/api/credentials");
  const el = document.getElementById("credentialsList");
  if (!creds.length) {
    el.innerHTML = `<div style="color:var(--muted); font-size:0.85rem;">No credentials saved yet. Use the Quick-Add SSO buttons above to add Google, LinkedIn, Microsoft, or Discord.</div>`;
    return;
  }
  el.innerHTML = `
    <table class="simple-table">
      <thead><tr><th>Site / Account</th><th>Provider</th><th>Domain</th><th>Username</th><th>Notes</th><th>Actions</th></tr></thead>
      <tbody>
        ${creds
          .map((c) => {
            const prov = c.auth_provider || "standard";
            const st = ssoStatusCache[prov];
            const isValid = st && (st === true || st.validated);
            const isRevoked = st && typeof st === "object" && st.revoked;
            const stateClass = isValid ? "btn-test-ok" : isRevoked ? "btn-test-fail" : "";
            const stateText = isValid ? "✅ Test SSO" : isRevoked ? "❌ Test SSO" : "Test SSO";
            const ssoTestBtn =
              prov !== "standard"
                ? `<button class="btn btn-secondary btn-sm test-sso-btn ${stateClass}" data-provider="${escapeHtml(prov)}" onclick="testSavedSso('${escapeJs(prov)}', this)">${stateText}</button>`
                : "";
            return `<tr>
            <td>${escapeHtml(c.site_name)}</td>
            <td><span class="badge ${prov !== "standard" ? "badge-sso" : ""}">${escapeHtml(prov)}</span></td>
            <td>${escapeHtml(c.site_domain)}</td>
            <td>${escapeHtml(c.username)}</td>
            <td>${escapeHtml(c.notes || "")}</td>
            <td class="row" style="gap:6px;">${ssoTestBtn}<button class="btn btn-danger btn-sm" onclick="deleteCred(${c.id})">Delete</button></td>
          </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;
}

async function saveCredential() {
  const payload = {
    site_name: document.getElementById("credName").value,
    site_domain: document.getElementById("credDomain").value,
    username: document.getElementById("credUser").value,
    password: document.getElementById("credPass").value,
    auth_provider: document.getElementById("credProvider").value,
    notes: document.getElementById("credNotes").value,
  };
  if (!payload.site_name || !payload.site_domain || !payload.username) {
    return alert("Site Name, Domain, and Username are required.");
  }
  await api("/api/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  document.getElementById("credPass").value = "";
  loadCredentials();
}

async function deleteCred(id) {
  await api(`/api/credentials/${id}`, { method: "DELETE" });
  loadCredentials();
}

// --- Settings & Multi-Agent Model Routing ---
const MODEL_CATALOG = [
  {
    group: "🦙 Local Ollama (100% Free & Offline)",
    options: [
      { value: "ollama:qwen2.5:7b", label: "Ollama Local: Qwen 2.5 7B (8GB+ VRAM GPU — Ultra Fast)" },
      { value: "ollama:gemma3:12b", label: "Ollama Local: Gemma 3 12B (Best in PT/EN/IT)" },
      { value: "ollama:qwen2.5:14b", label: "Ollama Local: Qwen 2.5 14B (Strong JSON & Writing)" },
      { value: "ollama:llama3.1:8b", label: "Ollama Local: Llama 3.1 8B (8GB+ VRAM GPU — Fast)" },
      { value: "ollama:mistral:latest", label: "Ollama Local: Mistral 7B" },
    ],
  },
  {
    group: "OpenRouter — Free Tier ($0)",
    options: [
      { value: "openrouter:google/gemma-3-27b-it:free", label: "OpenRouter Free: Gemma 3 27B (Great in PT/EN/IT)" },
      { value: "openrouter:meta-llama/llama-3.3-70b-instruct:free", label: "OpenRouter Free: Llama 3.3 70B" },
      { value: "openrouter:qwen/qwen3-32b:free", label: "OpenRouter Free: Qwen 3 32B" },
      { value: "openrouter:mistralai/mistral-small-3.1-24b-instruct:free", label: "OpenRouter Free: Mistral Small 3.1 24B" },
    ],
  },
  {
    group: "Google Gemini",
    options: [
      { value: "gemini:gemini-3.8-flash", label: "Gemini 3.8 Flash (Fast & Latest)" },
      { value: "gemini:gemini-3.5-flash", label: "Gemini 3.5 Flash (Fast & Stable)" },
      { value: "gemini:gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite (High Availability)" },
      { value: "gemini:gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite (Lightest)" },
    ],
  },
  {
    group: "OpenAI",
    options: [
      { value: "openai:gpt-4.1-mini", label: "OpenAI GPT-4.1 Mini (Fast & Cost-Effective)" },
      { value: "openai:gpt-4.1", label: "OpenAI GPT-4.1 (Strong Writing & Reasoning)" },
      { value: "openai:gpt-4o", label: "OpenAI GPT-4o" },
      { value: "openai:gpt-4o-mini", label: "OpenAI GPT-4o Mini" },
    ],
  },
  {
    group: "Anthropic Claude",
    options: [
      { value: "anthropic:claude-sonnet-4-20250514", label: "Claude Sonnet 4 (Top Executive Writing)" },
      { value: "anthropic:claude-3-7-sonnet-latest", label: "Claude 3.7 Sonnet" },
      { value: "anthropic:claude-3-5-haiku-latest", label: "Claude 3.5 Haiku (Fast)" },
    ],
  },
  {
    group: "OpenRouter — Paid (1 Key → All Vendors)",
    options: [
      { value: "openrouter:google/gemini-2.5-flash", label: "OpenRouter: Gemini 2.5 Flash" },
      { value: "openrouter:openai/gpt-4.1-mini", label: "OpenRouter: GPT-4.1 Mini" },
      { value: "openrouter:anthropic/claude-sonnet-4", label: "OpenRouter: Claude Sonnet 4" },
      { value: "openrouter:deepseek/deepseek-chat-v3-0324", label: "OpenRouter: DeepSeek V3" },
    ],
  },
];

const RECOMMENDED_BY_ROLE = {
  agentMatcherModel: {
    "ollama:qwen2.5:7b": "Recommended — Free Local",
    "gemini:gemini-3.8-flash": "Recommended — Cloud",
    "openrouter:google/gemma-3-27b-it:free": "Recommended — Free Cloud",
  },
  agentWriterModel: {
    "ollama:gemma3:12b": "Recommended — Free Local",
    "anthropic:claude-sonnet-4-20250514": "Recommended — Cloud",
    "openrouter:google/gemma-3-27b-it:free": "Recommended — Free Cloud",
  },
  agentFormModel: {
    "ollama:qwen2.5:7b": "Recommended — Free Local",
    "openai:gpt-4.1-mini": "Recommended — Cloud",
    "gemini:gemini-3.5-flash": "Recommended — Cloud",
  },
  agentFallbackModel: {
    "openrouter:google/gemma-3-27b-it:free": "Recommended — Free Failover",
    "ollama:qwen2.5:7b": "Recommended — Local Failover",
  },
};

function populateModelSelects() {
  document.querySelectorAll(".agent-model-select").forEach((sel) => {
    const allowNone = sel.dataset.allowNone === "true";
    const roleRecs = RECOMMENDED_BY_ROLE[sel.id] || {};
    let html = allowNone ? `<option value="">None (Use built-in fallback chain)</option>` : "";
    for (const grp of MODEL_CATALOG) {
      html += `<optgroup label="${escapeHtml(grp.group)}">`;
      for (const opt of grp.options) {
        const recTag = roleRecs[opt.value] ? ` ⭐ (${roleRecs[opt.value]})` : "";
        html += `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label + recTag)}</option>`;
      }
      html += `</optgroup>`;
    }
    sel.innerHTML = html;
  });
}

async function loadSettings() {
  populateModelSelects();
  const s = await api("/api/settings");
  const setStatus = (prov, has, preview) => {
    const el = document.getElementById(`apiKeyStatus-${prov}`);
    if (!el) return;
    el.textContent = has ? `(Saved: ${preview})` : "(Not set)";
    el.style.color = has ? "var(--success)" : "var(--muted)";
  };
  setStatus("gemini", s.has_gemini_api_key, s.gemini_api_key_preview);
  setStatus("openai", s.has_openai_api_key, s.openai_api_key_preview);
  setStatus("anthropic", s.has_anthropic_api_key, s.anthropic_api_key_preview);
  setStatus("openrouter", s.has_openrouter_api_key, s.openrouter_api_key_preview);
  const ollamaEl = document.getElementById("ollamaUrl");
  if (ollamaEl) ollamaEl.value = s.ollama_url || "";
  updateOllamaSetupButton(Boolean(s.ollama_ready));

  const setSelectVal = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined) el.value = val;
  };
  setSelectVal("agentMatcherModel", s.agent_matcher_model || "gemini:gemini-3.8-flash");
  setSelectVal("agentWriterModel", s.agent_writer_model || "gemini:gemini-3.8-flash");
  setSelectVal("agentFormModel", s.agent_form_model || "gemini:gemini-3.8-flash");
  setSelectVal("agentFallbackModel", s.agent_fallback_model || "");
}

async function saveSettings() {
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      gemini_api_key: document.getElementById("geminiKey").value,
      openai_api_key: document.getElementById("openaiKey").value,
      anthropic_api_key: document.getElementById("anthropicKey").value,
      openrouter_api_key: document.getElementById("openrouterKey").value,
      ollama_url: document.getElementById("ollamaUrl")?.value || "",
      agent_matcher_model: document.getElementById("agentMatcherModel").value,
      agent_writer_model: document.getElementById("agentWriterModel").value,
      agent_form_model: document.getElementById("agentFormModel").value,
      agent_fallback_model: document.getElementById("agentFallbackModel").value,
    }),
  });
  ["geminiKey", "openaiKey", "anthropicKey", "openrouterKey"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  await loadSettings();
  alert("AI providers & multi-agent routing saved!");
}

async function testProvider(provider) {
  try {
    const res = await api("/api/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });
    alert(`✅ ${res.provider.toUpperCase()} (${res.model}) connected! Reply: "${res.reply}"`);
  } catch (e) {
    alert(`❌ ${provider.toUpperCase()} test failed: ${e.message}`);
  }
}

function updateOllamaSetupButton(isReady) {
  const btn = document.getElementById("setupOllamaBtn");
  if (!btn) return;
  if (isReady) {
    btn.disabled = true;
    btn.textContent = "✅ Local Server Running";
    btn.classList.remove("btn-success");
    btn.classList.add("btn-secondary");
    btn.style.opacity = "0.55";
    btn.style.cursor = "not-allowed";
  } else {
    btn.disabled = false;
    btn.textContent = "⚡ Setup Local Server";
    btn.classList.remove("btn-secondary");
    btn.classList.add("btn-success");
    btn.style.opacity = "";
    btn.style.cursor = "";
  }
}

async function setupLocalOllama() {
  const btn = document.getElementById("setupOllamaBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Setting up…";
  }
  try {
    const res = await api("/api/ollama/setup", { method: "POST" });
    await loadSettings();
    if (res.status === "ready") {
      updateOllamaSetupButton(true);
    }
    alert(`🦙 ${res.message}`);
  } catch (e) {
    updateOllamaSetupButton(false);
    alert(`❌ Ollama setup failed: ${e.message}`);
  }
}

async function nuclearReset() {
  if (!confirm("Are you sure? This action will erase all information on the tool.")) {
    return;
  }
  if (!confirm("Are you sure SURE, buddy? There's no coming back from this!")) {
    return;
  }
  try {
    await api("/api/reset/nuclear", { method: "POST" });
    localStorage.clear();
    alert("☢️ Nuclear Reset complete. Everything has been scrubbed clean.");
    window.location.reload();
  } catch (e) {
    alert("Nuclear Reset failed: " + e.message);
  }
}

function renderMiniLogLine(l) {
  return `<div class="log-line log-${l.level || "info"}">[${(l.created_at || "").slice(11, 19)}] ${escapeHtml(l.message)}</div>`;
}

async function loadLogs() {
  const logs = await api("/api/logs?limit=80");
  const box = document.getElementById("logBox");
  const ordered = logs.slice().reverse();
  box.innerHTML = ordered.map(renderMiniLogLine).join("");
  box.scrollTop = box.scrollHeight;

  const mini = document.getElementById("agentMiniLog");
  if (mini) {
    mini.innerHTML = ordered.slice(-8).map(renderMiniLogLine).join("");
    mini.scrollTop = mini.scrollHeight;
  }
  const latest = ordered[ordered.length - 1];
  const curEl = document.getElementById("agentCurrentAction");
  if (curEl && latest) curEl.textContent = latest.message;
}

function appendLog(l) {
  const box = document.getElementById("logBox");
  const div = document.createElement("div");
  div.className = `log-line log-${l.level || "info"}`;
  div.textContent = `[${(l.created_at || "").slice(11, 19)}] ${l.message}`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;

  const mini = document.getElementById("agentMiniLog");
  if (mini) {
    const mdiv = div.cloneNode(true);
    mini.appendChild(mdiv);
    while (mini.children.length > 12) mini.removeChild(mini.firstChild);
    mini.scrollTop = mini.scrollHeight;
  }
  const curEl = document.getElementById("agentCurrentAction");
  if (curEl && l.message) curEl.textContent = l.message;
}

// --- Helpers ---
function closeModal(id) {
  document.getElementById(id).classList.remove("open");
}

function copyText(id) {
  const el = document.getElementById(id);
  const txt = el ? (el.value !== undefined ? el.value : el.textContent) : "";
  navigator.clipboard.writeText(txt || "");
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

function escapeJs(s) {
  return String(s || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

// Init
(async function init() {
  pickRandomTagline();
  bindAutoSaveListeners();
  connectSSE();
  await loadProfile();
  cvAnalysisLang = (profileCache.preferred_language || "pt").toLowerCase() === "en" ? "en" : "pt";
  await Promise.all([loadJobs(), loadStats(), loadDocuments(), loadCvAnalysis(), loadCredentials(), loadSsoStatus(), loadSettings(), loadLogs()]);
})();

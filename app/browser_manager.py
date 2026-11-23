"""Persistent headed Playwright Chromium manager with Human-in-the-Loop roadblock pause/resume."""

from __future__ import annotations

import asyncio
from typing import Any

from app import database as db
from app.config import BROWSER_PROFILE_DIR


class BrowserManager:
    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._lock = asyncio.Lock()

        # Roadblock coordination
        self.current_roadblock: dict[str, Any] | None = None
        self._roadblock_event: asyncio.Event | None = None
        self._roadblock_decision: str = "resume"  # "resume" | "skip" | "abort"

        # Event subscribers for live UI updates (SSE)
        self._subscribers: list[asyncio.Queue] = []

        # Track revoked SSO sessions (re-enables button if login expires or is denied)
        self._revoked_sso: set[str] = set()
        self._search_cancel_requested: bool = False

        # Live search progress state (capped at 50 results OR 5 minutes per search)
        self.search_progress: dict[str, Any] = {
            "active": False,
            "indexed": 0,
            "max_total": 50,
            "max_seconds": 300,
            "started_ts": 0.0,
            "deadline_ts": 0.0,
            "current_platform": "",
            "current_query": "",
            "percent": 0,
            "stop_reason": "",
        }

    def search_limit_reached(self) -> bool:
        import time

        if self._search_cancel_requested:
            self.search_progress["stop_reason"] = "Stopped by user"
            return True
        if not self.search_progress["active"]:
            return False
        if self.search_progress["indexed"] >= self.search_progress["max_total"]:
            self.search_progress["stop_reason"] = "Reached 50-job limit"
            return True
        deadline = self.search_progress.get("deadline_ts") or 0.0
        if deadline > 0 and time.time() >= deadline:
            self.search_progress["stop_reason"] = "Reached 5-minute time limit"
            return True
        return False

    async def request_search_stop(self) -> None:
        self._search_cancel_requested = True
        self.search_progress["stop_reason"] = "Stopped by user"
        if self._roadblock_event is not None:
            self.resolve_roadblock("abort")
        await self.log("🛑 Stop requested by user. Interrupting search after current item...", level="warning")

    async def start_search_progress(self, max_total: int = 50, max_seconds: int = 300) -> None:
        import time

        self._search_cancel_requested = False

        cap = max(1, min(50, int(max_total or 50)))
        now = time.time()
        self.search_progress = {
            "active": True,
            "indexed": 0,
            "max_total": cap,
            "max_seconds": max_seconds,
            "started_ts": now,
            "deadline_ts": now + max_seconds,
            "current_platform": "Starting…",
            "current_query": "",
            "percent": 0,
            "stop_reason": "",
        }
        await self.emit("search_progress", dict(self.search_progress))

    async def update_search_progress(
        self,
        *,
        current_platform: str | None = None,
        current_query: str | None = None,
        increment: int = 0,
    ) -> None:
        if current_platform is not None:
            self.search_progress["current_platform"] = current_platform
        if current_query is not None:
            self.search_progress["current_query"] = current_query
        if increment:
            self.search_progress["indexed"] = min(
                self.search_progress["max_total"],
                self.search_progress["indexed"] + increment,
            )
        max_t = max(1, self.search_progress["max_total"])
        self.search_progress["percent"] = min(100, int((self.search_progress["indexed"] / max_t) * 100))
        await self.emit("search_progress", dict(self.search_progress))

    async def finish_search_progress(self) -> None:
        self.search_progress["active"] = False
        self.search_progress["current_platform"] = "Completed"
        self.search_progress["percent"] = 100 if self.search_progress["indexed"] > 0 else 0
        await self.emit("search_progress", dict(self.search_progress))

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        msg = {"type": event_type, "data": payload}
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except Exception:
                pass

    async def log(self, message: str, level: str = "info", job_id: int | None = None) -> None:
        entry = await db.add_log(message, level=level, job_id=job_id)
        await self.emit("log", entry)

    async def ensure_browser(self):
        """Launch or reuse a persistent headed Chromium context."""
        async with self._lock:
            if self._context is not None:
                try:
                    # Verify context is still alive
                    _ = self._context.pages
                    return self._context
                except Exception:
                    self._context = None

            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            launch_kwargs = {
                "user_data_dir": str(BROWSER_PROFILE_DIR),
                "headless": False,
                "viewport": {"width": 1366, "height": 860},
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--start-minimized",
                ],
            }

            # Prefer signed system Chrome or Edge on Windows (avoids bundled chrome.dll 0x7E / OneDrive issues)
            last_err: Exception | None = None
            for channel in ("chrome", "msedge", None):
                try:
                    kwargs = dict(launch_kwargs)
                    if channel:
                        kwargs["channel"] = channel
                    self._context = await self._playwright.chromium.launch_persistent_context(**kwargs)
                    label = channel.upper() if channel else "Playwright Chromium"
                    # Keep browser minimized in background until user asks to see it or a roadblock occurs
                    await self._set_window_state("minimized")
                    await self.log(f"Interactive browser started in background using {label} (click 'Show Browser' anytime).", level="info")
                    return self._context
                except Exception as exc:
                    last_err = exc
                    continue

            raise RuntimeError(f"Could not launch Chrome, Edge, or Chromium: {last_err}")

    async def _set_window_state(self, state: str) -> None:
        """Set browser window state ('minimized' or 'normal') via Chrome DevTools Protocol."""
        if self._context is None:
            return
        try:
            pages = [p for p in self._context.pages if not p.is_closed()]
            page = pages[0] if pages else await self._context.new_page()
            cdp = await self._context.new_cdp_session(page)
            win = await cdp.send("Browser.getWindowForTarget")
            await cdp.send(
                "Browser.setWindowBounds",
                {"windowId": win["windowId"], "bounds": {"windowState": state}},
            )
            await cdp.detach()
        except Exception:
            pass

    async def show_browser(self) -> dict[str, Any]:
        """Restore and bring the interactive browser window to the foreground."""
        page = await self.get_active_page(bring_to_front=False)
        await self._set_window_state("normal")
        try:
            await page.bring_to_front()
        except Exception:
            pass
        return {"visible": True, "url": page.url}

    async def hide_browser(self) -> dict[str, Any]:
        """Minimize the interactive browser window back to the background."""
        if self._context is None:
            return {"visible": False}
        await self._set_window_state("minimized")
        return {"visible": False}

    async def get_active_page(self, bring_to_front: bool = False):
        ctx = await self.ensure_browser()
        try:
            pages = [p for p in ctx.pages if not p.is_closed()]
            page = pages[0] if pages else await ctx.new_page()
        except Exception:
            # Browser window was closed manually by the user; relaunch cleanly
            self._context = None
            ctx = await self.ensure_browser()
            pages = [p for p in ctx.pages if not p.is_closed()]
            page = pages[0] if pages else await ctx.new_page()
        if bring_to_front:
            await self._set_window_state("normal")
            await page.bring_to_front()
        return page

    SSO_PROVIDERS = {
        "google": {
            "name": "Google",
            "domain": "accounts.google.com",
            "login_url": "https://accounts.google.com/",
            "cookie_domains": ("google.com", "accounts.google.com"),
            "auth_cookies": ("SID", "HSID", "SSID", "APISID", "SAPISID", "__Secure-1PSID"),
        },
        "linkedin": {
            "name": "LinkedIn",
            "domain": "linkedin.com",
            "login_url": "https://www.linkedin.com/login",
            "cookie_domains": ("linkedin.com",),
            "auth_cookies": ("li_at",),
        },
        "microsoft": {
            "name": "Microsoft",
            "domain": "login.microsoftonline.com",
            "login_url": "https://login.microsoftonline.com/",
            "cookie_domains": ("microsoftonline.com", "live.com", "microsoft.com"),
            "auth_cookies": ("ESTSAUTH", "ESTSAUTHPERSISTENT", "MSPAuth", "RPSSecAuth"),
        },
        "discord": {
            "name": "Discord",
            "domain": "discord.com",
            "login_url": "https://discord.com/login",
            "cookie_domains": ("discord.com",),
            "auth_cookies": ("__dcfduid", "__sdcfduid", "cf_clearance"),
        },
    }

    async def connect_sso_provider(self, provider: str) -> dict[str, Any]:
        """Open the minibrowser to the SSO provider login page so session cookies persist automatically."""
        prov = (provider or "").strip().lower()
        if prov not in self.SSO_PROVIDERS:
            raise ValueError(f"Unsupported SSO provider: {provider}")
        self._revoked_sso.discard(prov)
        meta = self.SSO_PROVIDERS[prov]
        res = await self.open_interactive_url(meta["login_url"])

        # Register the SSO provider in the local vault as a browser-session login so it appears on roadblocks
        existing = await db.get_credential_by_provider(prov)
        if not existing:
            profile = await db.get_profile()
            await db.upsert_credential(
                site_name=f"{meta['name']} SSO",
                site_domain=meta["domain"],
                username=profile.get("email") or "Browser Session",
                password="",
                auth_provider=prov,
                notes="Authenticated via persistent browser session & cookies",
            )
        await self.log(
            f"Opened {meta['name']} login in minibrowser. Sign in there — once validated, session cookies are saved automatically.",
            level="info",
        )
        return {"provider": prov, "name": meta["name"], "url": res["url"]}

    async def get_sso_session_status(self) -> dict[str, dict[str, Any]]:
        """
        Validate live, non-expired authentication cookies in the persistent Chrome profile
        for each SSO provider. Returns {provider: {"validated": bool, "revoked": bool}}.
        """
        import time

        now = time.time()
        status: dict[str, dict[str, Any]] = {
            k: {"validated": False, "revoked": k in self._revoked_sso} for k in self.SSO_PROVIDERS
        }

        if self._context is not None:
            try:
                cookies = await self._context.cookies()
                for prov, meta in self.SSO_PROVIDERS.items():
                    if prov in self._revoked_sso:
                        continue
                    for ck in cookies:
                        dom = (ck.get("domain") or "").lower()
                        name = ck.get("name") or ""
                        exp = ck.get("expires", -1)
                        not_expired = (exp == -1) or (exp > now)
                        if not_expired and any(cd in dom for cd in meta["cookie_domains"]) and name in meta["auth_cookies"]:
                            status[prov]["validated"] = True
                            break
            except Exception:
                pass
        return status

    async def open_interactive_url(self, url: str) -> dict[str, Any]:
        """Open a URL in the persistent Chromium window and show it so the user can log in or create an account."""
        page = await self.get_active_page(bring_to_front=True)
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await self.show_browser()
        cred = await db.get_credential_for_url(url)
        await self.log(f"Opened interactive browser at {url}", level="info")
        return {
            "url": page.url,
            "title": await page.title(),
            "has_saved_credential": cred is not None,
        }

    async def _fill_login_inputs(self, page, username: str, password: str, two_step: bool = False) -> tuple[bool, bool]:
        filled_user = False
        filled_pass = False

        user_selectors = [
            "input[type='email']",
            "input[name='identifier']",
            "input[name='loginfmt']",
            "input[name='session_key']",
            "input[name='username']",
            "input[name='email']",
            "input[id*='username' i]",
            "input[id*='email' i]",
            "input[autocomplete='username']",
        ]
        pass_selectors = [
            "input[type='password']",
            "input[name='Passwd']",
            "input[name='passwd']",
            "input[name='session_password']",
            "input[name='password']",
            "input[autocomplete='current-password']",
        ]

        for sel in user_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.fill(username)
                filled_user = True
                break

        # For 2-step SSO flows (Google / Microsoft), click Next to reveal password input
        if filled_user and two_step:
            has_visible_pass = await page.locator("input[type='password']:visible").count() > 0
            if not has_visible_pass:
                for nxt in ("button:has-text('Next')", "button:has-text('Avançar')", "button:has-text('Avanti')", "input[type='submit']"):
                    btn = page.locator(nxt).first
                    if await btn.count() > 0 and await btn.is_visible():
                        try:
                            await btn.click()
                            await asyncio.sleep(2.5)
                        except Exception:
                            pass
                        break

        for sel in pass_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.fill(password)
                filled_pass = True
                break

        return filled_user, filled_pass

    async def autofill_saved_credentials(self, provider: str | None = None) -> dict[str, Any]:
        """
        Auto-fill credentials from the encrypted vault.
        When `provider` is 'google', 'linkedin', 'microsoft', or 'discord', first tries clicking
        the matching SSO button on the current site (e.g. 'Continue with Google'), then fills
        the saved provider credentials in the login page or popup.
        """
        page = await self.get_active_page()
        url = page.url

        sso_meta = {
            "google": {
                "domains": ("accounts.google.com", "google.com"),
                "labels": ("google", "gmail"),
                "two_step": True,
            },
            "linkedin": {
                "domains": ("linkedin.com",),
                "labels": ("linkedin",),
                "two_step": False,
            },
            "microsoft": {
                "domains": ("login.microsoftonline.com", "login.live.com", "microsoft.com"),
                "labels": ("microsoft", "outlook", "office 365", "entra"),
                "two_step": True,
            },
            "discord": {
                "domains": ("discord.com",),
                "labels": ("discord",),
                "two_step": False,
            },
        }

        prov = (provider or "").strip().lower()
        if prov in sso_meta:
            meta = sso_meta[prov]
            cred = await db.get_credential_by_provider(prov)
            if not cred:
                for dom in meta["domains"]:
                    cred = await db.get_credential_for_url(dom)
                    if cred:
                        break

            target_page = page
            clicked_sso = False
            # If not already on the SSO provider domain, look for and click the SSO button on the site
            if not any(d in page.url.lower() for d in meta["domains"]):
                before_pages = list(page.context.pages)
                for lbl in meta["labels"]:
                    candidates = page.locator(
                        f"button:has-text('{lbl}'), a:has-text('{lbl}'), [role='button']:has-text('{lbl}'), [aria-label*='{lbl}' i], [data-provider*='{lbl}' i]"
                    )
                    count = await candidates.count()
                    for i in range(min(count, 6)):
                        el = candidates.nth(i)
                        try:
                            if await el.is_visible():
                                await el.click(timeout=4000)
                                clicked_sso = True
                                await asyncio.sleep(2.5)
                                break
                        except Exception:
                            continue
                    if clicked_sso:
                        break

                if clicked_sso:
                    new_pages = [p for p in page.context.pages if p not in before_pages and not p.is_closed()]
                    if new_pages:
                        target_page = new_pages[-1]
                        await target_page.wait_for_load_state("domcontentloaded", timeout=20000)

            await self.show_browser()
            await target_page.bring_to_front()

            # If a password is also saved in the vault, fill login inputs; otherwise rely on persistent browser session cookies
            filled_user = False
            filled_pass = False
            if cred and cred.get("password"):
                filled_user, filled_pass = await self._fill_login_inputs(
                    target_page, cred["username"], cred["password"], two_step=meta["two_step"]
                )
            elif cred and cred.get("username") and cred["username"] != "Browser Session":
                # Click matching Google/Microsoft account tile if shown in account chooser
                tile = target_page.locator(f"[data-identifier='{cred['username']}'], div:has-text('{cred['username']}')").first
                if await tile.count() > 0 and await tile.is_visible():
                    try:
                        await tile.click(timeout=3000)
                        filled_user = True
                    except Exception:
                        pass

            msg = (
                f"SSO ({prov.title()}) triggered (clicked_button={clicked_sso}, user={filled_user}, pass={filled_pass}). "
                "Your persistent browser session will complete sign-in."
            )
            await self.log(msg, level="info")
            return {"filled": clicked_sso or filled_user or filled_pass, "message": msg}

        # Standard domain-matched autofill
        cred = await db.get_credential_for_url(url)
        if not cred:
            return {"filled": False, "message": f"No saved credentials found for {url}"}

        two_step = any(d in url.lower() for d in ("accounts.google.com", "login.microsoftonline.com", "login.live.com"))
        filled_user, filled_pass = await self._fill_login_inputs(
            page, cred["username"], cred["password"], two_step=two_step
        )
        await page.bring_to_front()
        msg = f"Auto-filled credentials for {cred['site_name']} (user={filled_user}, pass={filled_pass}). Complete login in the browser."
        await self.log(msg, level="info")
        return {"filled": filled_user or filled_pass, "message": msg}

    async def request_human_action(
        self,
        reason: str,
        url: str,
        job_id: int | None = None,
        job_title: str = "",
    ) -> str:
        """
        Pause automation and prompt the user in the Web UI to act in the interactive Chromium window.
        Returns the user's decision: 'resume', 'skip', or 'abort'.
        """
        cred = await db.get_credential_for_url(url)
        all_creds = await db.list_credentials()
        sso_providers = sorted(
            {
                c["auth_provider"]
                for c in all_creds
                if c.get("auth_provider") in ("google", "linkedin", "microsoft", "discord")
            }
        )
        self._roadblock_event = asyncio.Event()
        self._roadblock_decision = "resume"
        self.current_roadblock = {
            "job_id": job_id,
            "job_title": job_title,
            "reason": reason,
            "url": url,
            "has_saved_credential": cred is not None,
            "saved_site_name": cred["site_name"] if cred else "",
            "available_sso_providers": sso_providers,
        }

        try:
            await self.show_browser()
        except Exception:
            pass

        url_low = (url or "").lower()
        for prov, meta in self.SSO_PROVIDERS.items():
            if any(cd in url_low for cd in meta["cookie_domains"]) and any(
                k in url_low for k in ("/login", "/authwall", "/checkpoint", "/signin", "/uas/")
            ):
                self._revoked_sso.add(prov)
                await self.emit("sso_status", await self.get_sso_session_status())

        await self.log(f"ROADBLOCK ({job_title or 'Browser'}): {reason}", level="warning", job_id=job_id)
        await self.emit("roadblock", self.current_roadblock)

        await self._roadblock_event.wait()
        decision = self._roadblock_decision
        self.current_roadblock = None
        self._roadblock_event = None
        if decision == "resume":
            await self.hide_browser()
        await self.emit("roadblock_cleared", {"decision": decision})
        return decision

    def resolve_roadblock(self, decision: str = "resume") -> bool:
        if self._roadblock_event is None:
            return False
        self._roadblock_decision = decision if decision in ("resume", "skip", "abort") else "resume"
        self._roadblock_event.set()
        return True

    async def close(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


browser_manager = BrowserManager()

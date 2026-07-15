#!/usr/bin/env python3
"""
Polymarket Auto-Claim Bot v2 (Persistent Firefox)
===================================================

v2 improvements over v1:
  - Persistent Firefox: drivers kept alive between checks (no create/destroy every 4 min)
  - Periodic restart every 4 hours for memory cleanup
  - Google session keep-alive: navigates to accounts.google.com every 30 min
  - Better login retry: 3 attempts with increasing waits before giving up
  - Telegram alerts: notifies when autologin fails after all retries

Config (config.toml):
    # Optional Telegram alerts
    telegram_bot_token = "1234567890:AAAbbbCCCdddEEEfffGGGhhhIIIjjjKKK"
    telegram_chat_id = "12345678"

    [[accounts]]
    name = "Account 1"
    firefox_profile = "claimbot.default"

    [[accounts]]
    name = "Account 2"
    firefox_profile = "claimbot2.default"

Usage:
    python3 claim_bot_v2.py              # headless mode
    python3 claim_bot_v2.py --gui        # with GUI (VNC)
    python3 claim_bot_v2.py --login      # login mode (GUI, no loop)
"""

import os
import sentry_sdk
_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn:
    sentry_sdk.init(dsn=_sentry_dsn)

import argparse
import json
import time
import sys
import urllib.request
import urllib.parse
import traceback
from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException,
        NoSuchElementException,
        WebDriverException,
        InvalidSessionIdException,
    )
except ImportError:
    print("Install selenium: pip install selenium")
    sys.exit(1)


# =============================================================================
# CONSTANTS
# =============================================================================

CHECK_INTERVAL = 240                  # seconds between checks (4 min)
WAIT_AFTER_CLAIM = 60                 # seconds after claim/close
PAGE_LOAD_WAIT = 15                   # seconds for page load
DRIVER_RESTART_INTERVAL = 14400       # 4 hours — restart Firefox for memory cleanup
SESSION_KEEPALIVE_INTERVAL = 1800     # 30 min — visit Google to refresh session
MAX_LOGIN_RETRIES = 3                 # attempts before giving up
LOGIN_RETRY_WAITS = [5, 15, 30]       # seconds between retries (increasing)

# Firefox profile directories (snap + system)
FIREFOX_PROFILE_DIRS = [
    Path.home() / "snap/firefox/common/.mozilla/firefox",
    Path.home() / ".mozilla/firefox",
    Path.home() / ".config/mozilla/firefox",
]

# Paths
HOME = Path.home()
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.toml"
DATA_DIR = HOME / ".polymarket_bot"
LOG_FILE = DATA_DIR / "bot.log"


# =============================================================================
# CONFIG
# =============================================================================

def load_config() -> dict:
    """Load full config from config.toml. Returns dict with 'accounts' list and optional keys."""
    config = {
        "accounts": [{"name": "Default", "firefox_profile": ""}],
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "persistent": True,
    }

    if CONFIG_FILE.exists() and tomllib:
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
        accounts = data.get("accounts", [])
        if accounts:
            config["accounts"] = accounts
        config["telegram_bot_token"] = data.get("telegram_bot_token", "")
        config["telegram_chat_id"] = data.get("telegram_chat_id", "")
        if "persistent" in data:
            config["persistent"] = bool(data["persistent"])

    # Also check env vars as fallback
    if not config["telegram_bot_token"]:
        config["telegram_bot_token"] = os.environ.get("CLAIM_BOT_TG_TOKEN", "")
    if not config["telegram_chat_id"]:
        config["telegram_chat_id"] = os.environ.get("CLAIM_BOT_TG_CHAT", "")

    return config


def get_profile_path(account: dict) -> str:
    """Resolve Firefox profile path for an account."""
    profile_name = account.get("firefox_profile", "")

    for profiles_dir in FIREFOX_PROFILE_DIRS:
        if not profiles_dir.exists():
            continue

        if profile_name:
            # Exact match
            path = profiles_dir / profile_name
            if path.exists() and any(path.iterdir()):
                return str(path)

            # Partial match (e.g. "followdelta" matches "o02pisdx.followdelta")
            for item in profiles_dir.iterdir():
                if item.is_dir() and profile_name in item.name and any(item.iterdir()):
                    return str(item)

    # Fallback: find any .default profile with actual data
    for profiles_dir in FIREFOX_PROFILE_DIRS:
        if not profiles_dir.exists():
            continue
        for item in profiles_dir.iterdir():
            if item.is_dir() and ".default" in item.name and any(item.iterdir()):
                return str(item)

    return None


def get_state_file(account: dict) -> Path:
    """Get state file path for an account."""
    slug = account.get("name", "default").lower().replace(" ", "_")
    slug = "".join(c for c in slug if c.isalnum() or c == "_")
    return DATA_DIR / f"state_{slug}.json"


# =============================================================================
# STATE
# =============================================================================

def load_state(state_file: Path) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass
    return {"total_claimed": 0, "total_losses_closed": 0}


def save_state(state: dict, state_file: Path):
    state_file.write_text(json.dumps(state, indent=2))


# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str, tag: str = ""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{tag}] " if tag else ""
    line = f"[{timestamp}] {prefix}{msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def setup_dirs():
    DATA_DIR.mkdir(exist_ok=True)


# =============================================================================
# TELEGRAM ALERTS
# =============================================================================

def send_telegram_alert(token: str, chat_id: str, message: str):
    """Send a Telegram message. Non-blocking, never raises."""
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        log(f"Telegram alert failed: {e}")


# =============================================================================
# HELPERS
# =============================================================================

def is_settlement_window() -> bool:
    """Check if we're in a settlement window (+/-1 min from each 5-min cycle: :00, :05, :10, ...)"""
    now = datetime.now()
    cycle_sec = (now.minute % 5) * 60 + now.second
    return cycle_sec < 60 or cycle_sec >= 240


def monotonic_now() -> float:
    """Return monotonic clock (not affected by NTP jumps)."""
    return time.monotonic()


# =============================================================================
# FIREFOX / SELENIUM
# =============================================================================

def create_driver(profile_path: str, headless: bool = True):
    """Create a new Firefox WebDriver instance."""
    options = Options()
    options.binary_location = "/snap/firefox/current/usr/lib/firefox/firefox"
    options.add_argument("-profile")
    options.add_argument(profile_path)
    options.add_argument("-no-remote")

    if headless:
        options.add_argument("-headless")

    # Memory optimizations
    options.set_preference("permissions.default.image", 2)
    options.set_preference("browser.cache.disk.enable", False)
    options.set_preference("browser.cache.memory.enable", True)
    options.set_preference("browser.cache.memory.capacity", 16384)
    options.set_preference("toolkit.telemetry.enabled", False)
    options.set_preference("datareporting.healthreport.uploadEnabled", False)
    options.set_preference("browser.ping-centre.telemetry", False)
    options.set_preference("network.prefetch-next", False)
    options.set_preference("network.dns.disablePrefetch", True)
    options.set_preference("media.peerconnection.enabled", False)
    # Disable content processes to reduce memory footprint
    options.set_preference("dom.ipc.processCount", 1)
    # Disable session restore popups
    options.set_preference("browser.sessionstore.resume_from_crash", False)
    options.set_preference("browser.tabs.warnOnClose", False)
    options.add_argument("--width=800")
    options.add_argument("--height=600")

    driver = webdriver.Firefox(options=options)
    driver.set_page_load_timeout(30)
    return driver


def is_driver_alive(driver) -> bool:
    """Check if a WebDriver session is still valid."""
    if driver is None:
        return False
    try:
        _ = driver.title
        return True
    except (WebDriverException, InvalidSessionIdException, Exception):
        return False


def safe_quit_driver(driver, tag: str = ""):
    """Safely quit a driver, ignoring errors."""
    if driver is None:
        return
    try:
        driver.quit()
        log("Firefox closed", tag)
    except Exception:
        log("Firefox already dead, nothing to close", tag)


def find_login_button(driver):
    """Find the 'Log In' button on the page."""
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            try:
                if btn.text.strip() == "Log In":
                    return btn
            except Exception:
                continue
    except Exception:
        pass
    return None


def is_logged_in(driver) -> bool:
    """Check if user is logged in (no 'Log In' button present)."""
    return find_login_button(driver) is None


def find_google_button(driver):
    """Find 'Continue with Google' button in the login modal."""
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            try:
                text = btn.text.strip().lower()
                if "google" in text or "continue with google" in text:
                    return btn
            except Exception:
                continue

        elements = driver.find_elements(
            By.XPATH,
            "//*[contains(text(), 'Google') or contains(text(), 'google')]",
        )
        for el in elements:
            try:
                if el.is_displayed() and el.is_enabled():
                    if el.tag_name == "button":
                        return el
                    parent = el.find_element(By.XPATH, "./ancestor::button")
                    if parent:
                        return parent
            except Exception:
                continue
    except Exception as e:
        log(f"Error searching for Google button: {e}")
    return None


def _try_select_google_account(driver, tag: str = "") -> bool:
    """Try to find and click a Google account on the current page. Returns True if clicked."""
    # Selector 1: [data-email] (classic Google account chooser)
    try:
        accounts = driver.find_elements(By.CSS_SELECTOR, "[data-email]")
        if accounts:
            log(f"Found {len(accounts)} Google account(s) [data-email], selecting first...", tag)
            accounts[0].click()
            return True
    except Exception:
        pass

    # Selector 2: div with email text in account list
    try:
        items = driver.find_elements(By.CSS_SELECTOR, "div[data-identifier]")
        if items:
            log(f"Found {len(items)} Google account(s) [data-identifier], selecting first...", tag)
            items[0].click()
            return True
    except Exception:
        pass

    # Selector 3: li items in account chooser list
    try:
        items = driver.find_elements(By.CSS_SELECTOR, "ul li[role='link'], ul li[data-email]")
        if items:
            log(f"Found {len(items)} Google account(s) [li role=link], selecting first...", tag)
            items[0].click()
            return True
    except Exception:
        pass

    # Selector 4: clickable elements containing @ (email addresses)
    try:
        all_divs = driver.find_elements(By.XPATH, "//*[contains(text(), '@') and (self::div or self::span or self::a)]")
        for el in all_divs:
            txt = el.text.strip()
            if "@" in txt and "." in txt and el.is_displayed():
                log(f"Found email element '{txt[:30]}', clicking...", tag)
                el.click()
                return True
    except Exception:
        pass

    return False


def handle_login_attempt(driver, tag: str = "") -> bool:
    """Single login attempt. Handles both popup and same-window Google OAuth."""
    try:
        login_btn = find_login_button(driver)
        if not login_btn:
            return True  # Already logged in

        log("Clicking Log In...", tag)
        driver.execute_script("arguments[0].click();", login_btn)
        time.sleep(2)

        google_btn = find_google_button(driver)
        if not google_btn:
            log("Google button not found in modal", tag)
            return False

        log("Clicking Continue with Google...", tag)
        main_window = driver.current_window_handle
        windows_before = driver.window_handles
        url_before = driver.current_url

        driver.execute_script("arguments[0].click();", google_btn)
        time.sleep(3)

        windows_after = driver.window_handles
        url_after = driver.current_url

        # --- CASE 1: Google OAuth opened in a NEW popup window ---
        if len(windows_after) > len(windows_before):
            new_window = [w for w in windows_after if w not in windows_before][0]
            driver.switch_to.window(new_window)
            log(f"Google OAuth popup opened (URL: {driver.current_url[:60]}...)", tag)

            for _i in range(45):
                time.sleep(1)
                current_windows = driver.window_handles
                if new_window not in current_windows:
                    log("Google OAuth popup closed — login complete", tag)
                    driver.switch_to.window(main_window)
                    break
                # Try to select account
                _try_select_google_account(driver, tag)
            else:
                log(f"Timeout waiting for Google OAuth popup (URL: {driver.current_url[:80]})", tag)
                try:
                    driver.switch_to.window(main_window)
                except Exception:
                    pass
                return False

        # --- CASE 2: Google OAuth in SAME window (redirect) ---
        elif "accounts.google.com" in url_after or "google.com" in url_after:
            log(f"Google OAuth redirect in same window (URL: {url_after[:80]})", tag)

            for _i in range(45):
                time.sleep(1)
                cur_url = driver.current_url
                # Check if we're back on Polymarket
                if "polymarket.com" in cur_url:
                    log("Redirected back to Polymarket — login complete", tag)
                    break
                # Try to select account on Google page
                _try_select_google_account(driver, tag)
            else:
                log(f"Timeout on Google OAuth redirect (URL: {driver.current_url[:80]})", tag)
                # Force navigate back to Polymarket
                driver.get("https://polymarket.com/portfolio")
                time.sleep(PAGE_LOAD_WAIT)
                if is_logged_in(driver):
                    log("Login succeeded after force-redirect!", tag)
                    return True
                return False

        # --- CASE 3: No popup, no redirect — Privy handled it internally ---
        else:
            log(f"No popup/redirect detected (URL: {url_after[:60]}), waiting...", tag)
            # Wait for Privy to finish auth in-page
            time.sleep(8)

        # Wait for Privy to complete session setup after OAuth
        log("Waiting for Privy session...", tag)
        time.sleep(5)

        # Final check: navigate to portfolio and verify login
        log("Checking login status...", tag)
        driver.get("https://polymarket.com/portfolio")
        time.sleep(PAGE_LOAD_WAIT)

        if is_logged_in(driver):
            log("Auto-login via Google succeeded!", tag)
            return True

        # Retry: Privy might still be initializing, reload and check again
        log("First check failed, retrying after reload...", tag)
        driver.refresh()
        time.sleep(PAGE_LOAD_WAIT)

        if is_logged_in(driver):
            log("Auto-login succeeded on retry!", tag)
            return True
        else:
            log(f"Auto-login did not succeed (URL: {driver.current_url[:60]})", tag)
            return False

    except Exception as e:
        log(f"Error during auto-login: {e}", tag)
        return False


def handle_login_with_retries(driver, tag: str = "", max_retries: int = MAX_LOGIN_RETRIES) -> bool:
    """
    Attempt login up to max_retries times with increasing waits.
    Returns True if login succeeded, False if all attempts exhausted.
    """
    for attempt in range(max_retries):
        if attempt > 0:
            wait = LOGIN_RETRY_WAITS[min(attempt - 1, len(LOGIN_RETRY_WAITS) - 1)]
            log(f"Login retry {attempt + 1}/{max_retries} after {wait}s wait...", tag)
            time.sleep(wait)
            # Reload portfolio before retry
            try:
                driver.get("https://polymarket.com/portfolio")
                time.sleep(PAGE_LOAD_WAIT)
            except Exception as e:
                log(f"Failed to reload portfolio for retry: {e}", tag)
                return False

        success = handle_login_attempt(driver, tag)
        if success:
            if attempt > 0:
                log(f"Login succeeded on attempt {attempt + 1}/{max_retries}", tag)
            return True

    log(f"All {max_retries} login attempts failed!", tag)
    return False


# =============================================================================
# PERSISTENT DRIVER MANAGER
# =============================================================================

class DriverManager:
    """
    Manages persistent Firefox drivers for multiple accounts.

    Each account gets one long-lived driver. Drivers are:
    - Created on first use
    - Kept alive between check cycles (no create/destroy every 4 min)
    - Restarted every DRIVER_RESTART_INTERVAL for memory cleanup
    - Used for session keepalive pings to Google
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        # {account_name: driver}
        self._drivers: dict = {}
        # {account_name: monotonic timestamp of driver creation}
        self._driver_created_at: dict = {}
        # {account_name: monotonic timestamp of last keepalive}
        self._last_keepalive: dict = {}
        # {account_name: True} — accounts needing manual login
        self._needs_manual_login: dict = {}

    def get_or_create_driver(self, account_name: str, profile_path: str, tag: str = ""):
        """
        Get existing driver or create new one. Handles stale/crashed drivers.
        Returns driver or None on failure.
        """
        driver = self._drivers.get(account_name)
        created_at = self._driver_created_at.get(account_name, 0)
        now = monotonic_now()

        # Check if driver needs restart (stale / memory cleanup)
        needs_restart = False
        if driver is not None:
            if not is_driver_alive(driver):
                log("Driver is dead, recreating...", tag)
                safe_quit_driver(driver, tag)
                needs_restart = True
            elif (now - created_at) >= DRIVER_RESTART_INTERVAL:
                log(f"Driver age {int(now - created_at)}s >= {DRIVER_RESTART_INTERVAL}s, restarting for memory cleanup...", tag)
                safe_quit_driver(driver, tag)
                needs_restart = True

        if driver is None or needs_restart:
            try:
                log("Starting Firefox...", tag)
                driver = create_driver(profile_path, self.headless)
                self._drivers[account_name] = driver
                self._driver_created_at[account_name] = now
                self._last_keepalive[account_name] = now
                # Clear manual login flag on fresh driver
                self._needs_manual_login.pop(account_name, None)
                log("Firefox started, driver ready", tag)
            except Exception as e:
                log(f"Failed to create driver: {e}", tag)
                self._drivers.pop(account_name, None)
                self._driver_created_at.pop(account_name, None)
                return None

        return self._drivers.get(account_name)

    def mark_needs_manual_login(self, account_name: str):
        """Mark an account as needing manual login."""
        self._needs_manual_login[account_name] = True

    def needs_manual_login(self, account_name: str) -> bool:
        """Check if account is marked as needing manual login."""
        return self._needs_manual_login.get(account_name, False)

    def clear_manual_login(self, account_name: str):
        """Clear manual login flag (e.g. after successful auto-login)."""
        self._needs_manual_login.pop(account_name, None)

    def should_keepalive(self, account_name: str) -> bool:
        """Check if this account's driver needs a session keepalive ping."""
        last = self._last_keepalive.get(account_name, 0)
        return (monotonic_now() - last) >= SESSION_KEEPALIVE_INTERVAL

    def do_keepalive(self, account_name: str, tag: str = ""):
        """
        Navigate to accounts.google.com briefly to refresh Google session cookies.
        Then navigate back to a neutral page.
        """
        driver = self._drivers.get(account_name)
        if driver is None or not is_driver_alive(driver):
            return

        try:
            log("Session keepalive: visiting accounts.google.com...", tag)
            driver.get("https://accounts.google.com")
            time.sleep(3)
            # Navigate to a lightweight polymarket page to stay "warm"
            driver.get("https://polymarket.com/portfolio")
            time.sleep(5)
            self._last_keepalive[account_name] = monotonic_now()
            log("Session keepalive done", tag)
        except Exception as e:
            log(f"Session keepalive failed: {e}", tag)

    def shutdown_all(self):
        """Quit all drivers on shutdown."""
        for name, driver in self._drivers.items():
            safe_quit_driver(driver, name)
        self._drivers.clear()
        self._driver_created_at.clear()

    def get_driver_age(self, account_name: str) -> int:
        """Get driver age in seconds."""
        created_at = self._driver_created_at.get(account_name, monotonic_now())
        return int(monotonic_now() - created_at)


# =============================================================================
# CLAIM LOGIC
# =============================================================================

def run_single_check(
    driver,
    profile_path: str,
    state: dict,
    state_file: Path,
    tag: str = "",
    tg_token: str = "",
    tg_chat: str = "",
    driver_manager: DriverManager = None,
    account_name: str = "",
) -> bool:
    """
    Single check for one account using a persistent driver.
    Returns True if anything was claimed/closed.
    """
    claimed = False

    try:
        # Navigate to portfolio
        log("Loading portfolio...", tag)
        driver.get("https://polymarket.com/portfolio")
        time.sleep(PAGE_LOAD_WAIT)

        # Check login
        if not is_logged_in(driver):
            log("Not logged in, attempting auto-login with retries...", tag)
            success = handle_login_with_retries(driver, tag)
            if not success:
                msg = (
                    f"<b>Claim Bot Alert</b>\n\n"
                    f"Account <b>{tag}</b>: auto-login failed after {MAX_LOGIN_RETRIES} attempts.\n"
                    f"Manual VNC login required!"
                )
                log(f"AUTO-LOGIN FAILED for {tag}! Manual VNC login required.", tag)
                send_telegram_alert(tg_token, tg_chat, msg)
                if driver_manager and account_name:
                    driver_manager.mark_needs_manual_login(account_name)
                return False
            else:
                # Login succeeded, clear any manual login flag
                if driver_manager and account_name:
                    driver_manager.clear_manual_login(account_name)

        # === CLAIM ===
        claim_btn = None
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            try:
                if btn.text.strip() in ("Claim", "Redeem"):
                    claim_btn = btn
                    break
            except Exception:
                continue

        if claim_btn:
            log(f"Found {claim_btn.text.strip()} button, clicking...", tag)
            driver.execute_script("arguments[0].click();", claim_btn)
            time.sleep(3)

            buttons = driver.find_elements(By.TAG_NAME, "button")
            proceed_btn = None
            for btn in buttons:
                try:
                    text = btn.text.strip()
                    # Polymarket button variants:
                    # "Claim $4,547.26" (old UI with dollar sign)
                    # "Claim 56.17" (new UI without dollar sign)
                    # "Claim proceeds" (legacy UI)
                    if text.startswith("Claim $") or text.startswith("Claim ") and any(c.isdigit() for c in text) or "Claim proceeds" in text or text.startswith("Redeem $") or text.startswith("Redeem ") and any(c.isdigit() for c in text) or "Redeem proceeds" in text:
                        proceed_btn = btn
                        break
                except Exception:
                    continue

            if proceed_btn:
                log(f"Clicking '{proceed_btn.text.strip()}'...", tag)
                driver.execute_script("arguments[0].click();", proceed_btn)
                state["total_claimed"] += 1
                save_state(state, state_file)
                log(f"Claim #{state['total_claimed']} done!", tag)
                time.sleep(WAIT_AFTER_CLAIM)
                claimed = True
            else:
                log("Claim confirmation button not found", tag)
        else:
            log("No Claim/Redeem button found - nothing to claim", tag)

        # === CLOSE LOSSES (History tab) ===
        log("Loading History for Close Losses check...", tag)
        driver.get("https://polymarket.com/portfolio?tab=history")
        time.sleep(PAGE_LOAD_WAIT)

        close_losses_btn = None
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            try:
                text = btn.text.strip()
                if text in ("Close Losses", "Close losses"):
                    close_losses_btn = btn
                    break
            except Exception:
                continue

        if close_losses_btn:
            log("Found Close Losses button, clicking...", tag)
            driver.execute_script("arguments[0].click();", close_losses_btn)
            time.sleep(5)

            confirm_btn = None
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                try:
                    text = btn.text.strip()
                    if "Close" in text and text not in ("Close Losses", "Close losses"):
                        confirm_btn = btn
                        break
                except Exception:
                    continue

            if confirm_btn:
                driver.execute_script("arguments[0].click();", confirm_btn)

            state["total_losses_closed"] = state.get("total_losses_closed", 0) + 1
            save_state(state, state_file)
            log(f"Close Losses #{state['total_losses_closed']} done!", tag)
            time.sleep(WAIT_AFTER_CLAIM)
            claimed = True
        else:
            log("No Close Losses button on History", tag)

    except TimeoutException:
        log("Page load timeout", tag)
    except (WebDriverException, InvalidSessionIdException) as e:
        log(f"Driver error (will be recreated next cycle): {e}", tag)
        # Force driver recreation on next get_or_create_driver call
        if driver_manager and account_name:
            driver_manager._drivers.pop(account_name, None)
    except Exception as e:
        log(f"Error: {e}", tag)
        sentry_sdk.capture_exception(e)

    return claimed


# =============================================================================
# LOGIN MODE
# =============================================================================

def run_login_mode(accounts: list):
    """Open Firefox with GUI for each account for manual login."""
    for acc in accounts:
        name = acc.get("name", "?")
        profile_path = get_profile_path(acc)
        if not profile_path:
            log(f"Profile not found for {name}", name)
            continue

        log(f"Opening Firefox for manual login...", name)
        log(f"Profile: {profile_path}", name)
        log(f"Log into Google -> Polymarket, then close the browser.", name)

        driver = create_driver(profile_path, headless=False)
        driver.get("https://polymarket.com")

        log("Waiting for browser to close...", name)
        try:
            while True:
                try:
                    _ = driver.title
                    time.sleep(2)
                except Exception:
                    break
        except Exception:
            pass

        log("Browser closed, moving to next account", name)
        time.sleep(1)

    log("All accounts processed. Now start the bot without --login.")


# =============================================================================
# MAIN LOOP
# =============================================================================

def run_bot(accounts: list, headless: bool = True, tg_token: str = "", tg_chat: str = "",
            persistent: bool = True):
    setup_dirs()

    log("=" * 60)
    mode_str = "persistent" if persistent else "sequential (non-persistent)"
    log(f"Polymarket Auto-Claim Bot v2 ({mode_str})")
    log(f"  Accounts: {len(accounts)}")
    log(f"  Mode: {'headless' if headless else 'GUI'}")
    log(f"  Persistent drivers: {persistent}")
    log(f"  Check interval: {CHECK_INTERVAL}s ({CHECK_INTERVAL // 60} min)")
    if persistent:
        log(f"  Driver restart: every {DRIVER_RESTART_INTERVAL}s ({DRIVER_RESTART_INTERVAL // 3600}h)")
        log(f"  Session keepalive: every {SESSION_KEEPALIVE_INTERVAL}s ({SESSION_KEEPALIVE_INTERVAL // 60} min)")
    log(f"  Login retries: {MAX_LOGIN_RETRIES}")
    log(f"  Telegram alerts: {'enabled' if (tg_token and tg_chat) else 'disabled'}")
    log("=" * 60)

    # Validate profiles
    account_profiles = []
    for acc in accounts:
        name = acc.get("name", "?")
        profile_path = get_profile_path(acc)
        state_file = get_state_file(acc)
        state = load_state(state_file)

        if not profile_path:
            log(f"ERROR: Firefox profile not found!", name)
            continue

        log(f"  [{name}] profile={Path(profile_path).name} claims={state['total_claimed']} losses={state.get('total_losses_closed', 0)}")
        account_profiles.append((acc, name, profile_path, state_file))

    if not account_profiles:
        log("No valid accounts!")
        return

    log("=" * 60)

    # Create driver manager (only used in persistent mode)
    dm = DriverManager(headless=headless) if persistent else None

    # Track last time we ran keepalive (global, not per-account — we do all at once)
    last_keepalive_run = monotonic_now()

    try:
        while True:
            try:
                # --- Settlement window skip ---
                if is_settlement_window():
                    now = datetime.now()
                    cycle_sec = (now.minute % 5) * 60 + now.second
                    if cycle_sec < 60:
                        wait_sec = 60 - cycle_sec
                    else:
                        wait_sec = (300 - cycle_sec) + 60
                    wait_sec = max(wait_sec, 10)
                    resume_time = datetime.fromtimestamp(
                        now.timestamp() + wait_sec
                    ).strftime("%H:%M:%S")
                    log(f"Settlement window - skipping. Resume at {resume_time}")
                    time.sleep(wait_sec)
                    continue

                if persistent:
                    # --- PERSISTENT MODE ---
                    # Session keepalive (every 30 min)
                    now_mono = monotonic_now()
                    if (now_mono - last_keepalive_run) >= SESSION_KEEPALIVE_INTERVAL:
                        log("--- Running session keepalive for all accounts ---")
                        for acc, name, profile_path, state_file in account_profiles:
                            if dm.needs_manual_login(name):
                                continue
                            driver = dm._drivers.get(name)
                            if driver is not None and is_driver_alive(driver):
                                dm.do_keepalive(name, tag=name)
                                time.sleep(2)
                        last_keepalive_run = monotonic_now()
                        log("--- Session keepalive complete ---")

                    # Check each account with persistent driver
                    for acc, name, profile_path, state_file in account_profiles:
                        if dm.needs_manual_login(name):
                            log(f"Account marked as needs_manual_login, attempting recovery...", name)

                        driver = dm.get_or_create_driver(name, profile_path, tag=name)
                        if driver is None:
                            log(f"Could not create driver, skipping", name)
                            continue

                        state = load_state(state_file)
                        run_single_check(
                            driver=driver, profile_path=profile_path,
                            state=state, state_file=state_file, tag=name,
                            tg_token=tg_token, tg_chat=tg_chat,
                            driver_manager=dm, account_name=name,
                        )
                        if len(account_profiles) > 1:
                            time.sleep(5)

                    # Log driver ages
                    next_check = datetime.now().timestamp() + CHECK_INTERVAL
                    next_time = datetime.fromtimestamp(next_check).strftime("%H:%M:%S")
                    driver_ages = ", ".join(
                        f"{name}={dm.get_driver_age(name)}s"
                        for _, name, _, _ in account_profiles
                        if name in dm._drivers
                    )
                    log(f"Next check at {next_time} | Driver ages: {driver_ages}")

                else:
                    # --- NON-PERSISTENT MODE (sequential, one Firefox at a time) ---
                    for acc, name, profile_path, state_file in account_profiles:
                        driver = None
                        try:
                            log("Starting Firefox...", name)
                            driver = create_driver(profile_path, headless)
                            state = load_state(state_file)
                            run_single_check(
                                driver=driver, profile_path=profile_path,
                                state=state, state_file=state_file, tag=name,
                                tg_token=tg_token, tg_chat=tg_chat,
                            )
                        except Exception as e:
                            log(f"Error: {e}", name)
                        finally:
                            safe_quit_driver(driver, name)
                        if len(account_profiles) > 1:
                            time.sleep(5)

                    next_check = datetime.now().timestamp() + CHECK_INTERVAL
                    next_time = datetime.fromtimestamp(next_check).strftime("%H:%M:%S")
                    log(f"Next check at {next_time} ({CHECK_INTERVAL // 60} min)")

                log("-" * 60)
                time.sleep(CHECK_INTERVAL)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"Error in main loop: {e}")
                sentry_sdk.capture_exception(e)
                time.sleep(60)

    except KeyboardInterrupt:
        log("Stopping (Ctrl+C)...")
    finally:
        if dm:
            log("Shutting down all drivers...")
            dm.shutdown_all()
        log("All drivers closed. Goodbye.")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Auto-Claim Bot v2 (Persistent Firefox)"
    )
    parser.add_argument(
        "--gui", action="store_true", help="Run with GUI (for debugging via VNC)"
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Login mode - open Firefox for each account for manual login",
    )
    args = parser.parse_args()

    config = load_config()
    accounts = config["accounts"]
    tg_token = config["telegram_bot_token"]
    tg_chat = config["telegram_chat_id"]

    persistent = config.get("persistent", True)

    if args.login:
        run_login_mode(accounts)
    else:
        run_bot(
            accounts,
            headless=not args.gui,
            tg_token=tg_token,
            tg_chat=tg_chat,
            persistent=persistent,
        )


if __name__ == "__main__":
    main()

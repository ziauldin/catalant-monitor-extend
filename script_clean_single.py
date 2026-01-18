import time
import smtplib
import json
import os
import re
import traceback
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Load environment variables (Railway will provide env vars; .env is for local)
load_dotenv()


# ============================
# CONFIGURATION
# ============================

class Config:
    """Load configuration from environment variables"""
    CATALANT_EMAIL = os.getenv("CATALANT_EMAIL")
    CATALANT_PASSWORD = os.getenv("CATALANT_PASSWORD")

    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

    RECIPIENT_EMAILS = [e.strip() for e in os.getenv("RECIPIENT_EMAILS", "").split(",") if e.strip()]

    HEADLESS = os.getenv("HEADLESS", "True").lower() == "true"

    # Playwright session state (recommended over raw cookies)
    STORAGE_STATE_FILE = os.getenv("STORAGE_STATE_FILE", "catalant_state.json")

    # Hard-coded PROJECTS_DB - always use seen_projects.json
    PROJECTS_DB = "seen_projects.json"
    
    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))

    # If you ever want images enabled, set DISABLE_IMAGES=false
    DISABLE_IMAGES = os.getenv("DISABLE_IMAGES", "True").lower() == "true"

    # Increase these for cloud stability - higher defaults for Railway
    NAV_TIMEOUT_MS = int(os.getenv("NAV_TIMEOUT_MS", "90000"))
    ACTION_TIMEOUT_MS = int(os.getenv("ACTION_TIMEOUT_MS", "60000"))

    # Watchdog: planned restart to prevent long-running Railway memory issues
    WATCHDOG_RESTART_SECONDS = int(os.getenv("WATCHDOG_RESTART_SECONDS", "14400"))  # 4 hours
    WATCHDOG_MAX_CYCLES = int(os.getenv("WATCHDOG_MAX_CYCLES", "0"))  # 0 = disabled


def validate_env():
    missing = []
    if not Config.CATALANT_EMAIL:
        missing.append("CATALANT_EMAIL")
    if not Config.CATALANT_PASSWORD:
        missing.append("CATALANT_PASSWORD")
    if not Config.SMTP_SERVER:
        missing.append("SMTP_SERVER")
    if not Config.SENDER_EMAIL:
        missing.append("SENDER_EMAIL")
    if not Config.SENDER_PASSWORD:
        missing.append("SENDER_PASSWORD")
    if not Config.RECIPIENT_EMAILS:
        missing.append("RECIPIENT_EMAILS")

    if missing:
        print("❌ Missing env vars:", ", ".join(missing))
        print("👉 Add them in Railway > Variables")
        return False
    return True


# ============================
# EMAIL NOTIFICATIONS
# ============================

def create_email_html(project):
    categories_html = ""
    if project.get("categories"):
        cats = "<br>".join([f"• {cat}" for cat in project["categories"]])
        categories_html = f"<div style='margin: 10px 0;'><strong>📁 Categories:</strong><br>{cats}</div>"

    description = project.get("description", "No description available").replace("\n", "<br>")

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 800px; margin: 0 auto; padding: 20px;">
            <div style="background:#4CAF50; color:#fff; padding:15px; border-radius:8px 8px 0 0;">
                <h2 style="margin:0;">🚀 New Project on Catalant</h2>
            </div>

            <div style="padding:20px; border:1px solid #ddd; border-top:none; border-radius:0 0 8px 8px;">
                <h3 style="margin-top:0;">{project.get("title","Untitled Project")}</h3>

                <div style="background:#f8f9fa; padding:15px; border-radius:8px; margin:15px 0;">
                    <p style="margin:5px 0;"><strong>📍 Location:</strong> {project.get("location","Remote / Not specified")}</p>
                    <p style="margin:5px 0;"><strong>⏰ Posted:</strong> {project.get("time_posted","Unknown")} ago</p>
                    <p style="margin:5px 0;"><strong>🆔 Project ID:</strong> {project.get("id","N/A")}</p>
                    <p style="margin:5px 0;"><strong>🕒 Detected:</strong> {project.get("detected_at","")}</p>
                </div>

                {categories_html}

                <div style="background:#fff; padding:15px; border-left:4px solid #4CAF50; margin:15px 0;">
                    <h4 style="margin-top:0;">📋 Project Description</h4>
                    <p>{description}</p>
                </div>

                <div style="text-align:center; margin-top:20px;">
                    <a href="https://app.gocatalant.com/c/_/u/0/dashboard/"
                       style="display:inline-block; background:#4CAF50; color:#fff; padding:12px 24px; text-decoration:none; border-radius:8px;">
                       View on Catalant Dashboard
                    </a>
                </div>

                <p style="margin-top:20px; font-size:12px; color:#777;">
                    Automated notification from Catalant Project Monitor
                </p>
            </div>
        </div>
    </body>
    </html>
    """


def send_notification(project):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔔 Catalant: {project.get('title', 'New Project')}"
        msg["From"] = Config.SENDER_EMAIL
        msg["To"] = ", ".join(Config.RECIPIENT_EMAILS)

        msg.attach(MIMEText(create_email_html(project), "html"))

        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SENDER_EMAIL, Config.SENDER_PASSWORD)
            server.send_message(msg)

        print(f"📧 Email sent: {project.get('title','Unknown')[:70]}...")
        return True
    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False


# ============================
# PROJECT DATABASE
# ============================

def load_seen_projects():
    if not os.path.exists(Config.PROJECTS_DB):
        return []
    try:
        with open(Config.PROJECTS_DB, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Validate that data is a list of dictionaries
            if not isinstance(data, list):
                print("⚠️ Invalid format in seen_projects.json (not a list), resetting...")
                return []
            # Filter out any non-dict items
            valid_projects = [p for p in data if isinstance(p, dict)]
            if len(valid_projects) != len(data):
                print(f"⚠️ Filtered out {len(data) - len(valid_projects)} invalid entries")
            return valid_projects
    except Exception as e:
        print(f"⚠️ Failed to load projects: {e}")
        return []


def save_seen_projects(projects):
    try:
        # Validate that we're saving a list of dicts
        if not isinstance(projects, list):
            print("⚠️ Cannot save: projects is not a list")
            return
        # Filter out any non-dict items before saving
        valid_projects = [p for p in projects if isinstance(p, dict) and p.get("id")]
        with open(Config.PROJECTS_DB, "w", encoding="utf-8") as f:
            json.dump(valid_projects, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Failed to save projects: {e}")


def filter_new_projects(all_projects, seen_projects):
    # Defensive: ensure seen_projects is a list of dicts
    if not isinstance(seen_projects, list):
        print("⚠️ seen_projects is not a list, treating as empty")
        seen_projects = []
    
    # Extract IDs, handling any non-dict items gracefully
    seen_ids = set()
    for p in seen_projects:
        if isinstance(p, dict) and p.get("id"):
            seen_ids.add(p["id"])
        elif not isinstance(p, dict):
            print(f"⚠️ Skipping invalid entry in seen_projects: {type(p).__name__}")
    
    # Filter new projects
    return [p for p in all_projects if isinstance(p, dict) and p.get("id") and p["id"] not in seen_ids]


# ============================
# PLAYWRIGHT: SESSION + SCRAPE
# ============================

DASHBOARD_URL = "https://app.gocatalant.com/c/_/u/0/dashboard/"


def _route_block_images(route, request):
    # Block images/media/fonts to reduce bandwidth & memory
    if request.resource_type in ("image", "media", "font"):
        return route.abort()
    return route.continue_()


def is_logged_in(page) -> bool:
    """Check if logged in, catching any Target crashed or page errors"""
    try:
        return page.locator(".need-card-inline-name").count() > 0
    except Exception as e:
        print(f"⚠️ is_logged_in check failed (possibly crashed): {e}")
        return False


def perform_login(page) -> bool:
    """
    Robust login that works when:
    - email input is editable
    - OR email input is readonly but already prefilled
    - OR there is a Continue/Next step before password
    """
    try:
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=Config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(1500)

        email = page.locator('input[name="email"], #email-id').first
        email.wait_for(timeout=Config.ACTION_TIMEOUT_MS)

        # Read current value + readonly state
        current_val = ""
        try:
            current_val = (email.input_value() or "").strip()
        except Exception:
            pass

        is_readonly = False
        try:
            is_readonly = bool(email.get_attribute("readonly"))
        except Exception:
            pass

        # Only set email if needed / possible
        if is_readonly and current_val:
            print(f"ℹ️ Email is readonly and already set to: {current_val}")
        else:
            # Type email via keyboard for better reliability
            email.click(force=True, timeout=Config.ACTION_TIMEOUT_MS)
            page.keyboard.press("Control+A")
            page.keyboard.type(Config.CATALANT_EMAIL, delay=50)

        # If there is an email-first step
        if page.locator('button:has-text("Continue")').count() > 0:
            page.click('button:has-text("Continue")', timeout=Config.ACTION_TIMEOUT_MS)
            page.wait_for_timeout(1200)
        elif page.locator('button:has-text("Next")').count() > 0:
            page.click('button:has-text("Next")', timeout=Config.ACTION_TIMEOUT_MS)
            page.wait_for_timeout(1200)

        # Wait for password field
        password = page.locator('input[name="password"]').first
        password.wait_for(timeout=Config.ACTION_TIMEOUT_MS)

        # Type password via keyboard
        password.click(force=True, timeout=Config.ACTION_TIMEOUT_MS)
        page.keyboard.press("Control+A")
        page.keyboard.type(Config.CATALANT_PASSWORD, delay=50)

        # Submit
        if page.locator('button:has-text("Login")').count() > 0:
            page.click('button:has-text("Login")', timeout=Config.ACTION_TIMEOUT_MS)
        else:
            page.click('button[type="submit"]', timeout=Config.ACTION_TIMEOUT_MS)

        # Confirm dashboard
        page.wait_for_selector(".need-card-inline-name", timeout=Config.NAV_TIMEOUT_MS)
        print("✅ Login successful")
        return True

    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False


def setup_session(context, page) -> bool:
    """
    Uses storage_state if present; otherwise logs in and saves storage_state.
    Catches Target crashed and navigation errors.
    """
    try:
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=Config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)

        if is_logged_in(page):
            print("✅ Logged in via saved session (storage_state)")
            return True

        ok = perform_login(page)
        if ok:
            try:
                context.storage_state(path=Config.STORAGE_STATE_FILE)
                print(f"✅ Saved session state: {Config.STORAGE_STATE_FILE}")
            except Exception as e:
                print(f"⚠️ Could not save storage_state: {e}")
        return ok

    except PlaywrightTimeoutError as e:
        print(f"❌ Session setup timeout: {e}")
        return False
    except Exception as e:
        # Catch "Target crashed" and other errors
        print(f"❌ Session setup failed: {e}")
        return False


def extract_project_data_from_card(card) -> dict | None:
    try:
        title = card.locator(".need-card-inline-name .line-clamp-2").first.inner_text().strip()
        if not title:
            return None

        project_id = None
        like_btn = card.locator("[data-ajax-post*='need/']").first
        if like_btn.count() > 0:
            ajax = like_btn.get_attribute("data-ajax-post") or ""
            m = re.search(r"/need/([^/]+)/", ajax)
            if m:
                project_id = m.group(1)
        if not project_id:
            return None

        categories = []
        cat_loc = card.locator(".need-card-inline-pools .small.text-muted").first
        if cat_loc.count() > 0:
            cat_text = cat_loc.inner_text().strip()
            if cat_text:
                categories = [c.strip() for c in cat_text.split("|") if c.strip()]

        description = ""
        desc_loc = card.locator(".need-card-inline-details .line-clamp-2").first
        if desc_loc.count() > 0:
            description = desc_loc.inner_text().strip()

        location = ""
        loc_loc = card.locator(".text-gray-25.font-weight-semibold").first
        if loc_loc.count() > 0:
            location = (loc_loc.inner_text() or "").replace("Remote", "").strip()

        time_posted = "Unknown"
        posted_loc = card.locator("span:has-text('Posted')").first
        if posted_loc.count() > 0:
            txt = posted_loc.inner_text().strip()
            time_posted = txt.replace("Posted", "").replace("ago", "").strip()

        status = "Posted"
        if card.locator(".badge-success").count() > 0:
            status = "New Project"

        return {
            "id": project_id,
            "title": title,
            "categories": categories,
            "description": description,
            "location": location,
            "time_posted": time_posted,
            "status": status,
            "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception:
        return None


def scan_for_projects(page) -> list[dict]:
    try:
        page.wait_for_selector(".need-card-inline-name", timeout=Config.NAV_TIMEOUT_MS)

        cards = page.locator("div.card-block").all()
        projects = []

        for card in cards:
            if card.locator(".need-card-inline").count() == 0:
                continue
            proj = extract_project_data_from_card(card)
            if proj and proj.get("id") and proj.get("title"):
                projects.append(proj)

        print(f"✅ Extracted {len(projects)} valid projects")
        return projects

    except PlaywrightTimeoutError:
        print("⏳ Timeout waiting for projects")
        return []
    except Exception as e:
        print(f"❌ Error scanning: {e}")
        return []


def run_once() -> bool:
    """
    Run one scrape cycle. Returns True on success, False on failure.
    Catches Target crashed, navigation timeouts, and other errors.
    """
    print("=" * 60)
    print(f"🔄 Cycle started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    browser = None
    context = None
    page = None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=Config.HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--window-size=1920,1080",
                ],
            )

            # Load storage state if present (keeps you logged in across restarts)
            storage_state = Config.STORAGE_STATE_FILE if os.path.exists(Config.STORAGE_STATE_FILE) else None

            context = browser.new_context(
                storage_state=storage_state,
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            context.set_default_timeout(Config.ACTION_TIMEOUT_MS)
            context.set_default_navigation_timeout(Config.NAV_TIMEOUT_MS)

            if Config.DISABLE_IMAGES:
                context.route("**/*", _route_block_images)

            page = context.new_page()

            if not setup_session(context, page):
                print("❌ Failed to establish session")
                return False

            seen_projects = load_seen_projects()
            print(f"📁 Loaded {len(seen_projects)} seen projects")

            all_projects = scan_for_projects(page)
            if not all_projects:
                print("⚠️ No projects found (or page didn't load)")
                # Not necessarily a failure - might just be empty
                return True

            new_projects = filter_new_projects(all_projects, seen_projects)

            if new_projects:
                print(f"🎯 Found {len(new_projects)} NEW project(s)!")
                for project in new_projects:
                    print(f"  → {project['title'][:90]}...")
                    send_notification(project)
                    seen_projects.append(project)

                save_seen_projects(seen_projects)
                print("✅ Updated seen_projects.json")
            else:
                print("⏳ No new projects")

            print(f"📊 Stats: {len(all_projects)} total, {len(seen_projects)} tracked")
            return True

    except PlaywrightTimeoutError as e:
        print(f"❌ Navigation timeout: {e}")
        return False
    except Exception as e:
        # Catch Target crashed and other errors
        error_msg = str(e).lower()
        if "target crashed" in error_msg or "connection closed" in error_msg:
            print(f"❌ Browser/target crashed: {e}")
        else:
            print(f"❌ Cycle error: {e}")
            traceback.print_exc()
        return False
    finally:
        # Ensure proper cleanup in correct order
        if page:
            try:
                page.close()
            except Exception:
                pass
        
        if context:
            try:
                context.close()
            except Exception:
                pass
        
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        
        print("✅ Cleanup complete")


def worker_loop(interval_seconds: int):
    """
    Main loop with exponential backoff on failures.
    - Starts backoff at 120 seconds
    - Doubles on each failure up to max 900 seconds
    - Resets to 120 seconds on success
    - On success, uses normal CHECK_INTERVAL_SECONDS
    - On failure, waits current backoff delay
    """
    print("🟢 Worker started (Playwright)")
    print(f"⏱️ Normal interval: {interval_seconds}s ({interval_seconds // 60} minutes)")
    
    # Watchdog tracking
    start_time = time.time()
    cycle_count = 0
    
    if Config.WATCHDOG_RESTART_SECONDS > 0:
        restart_hours = Config.WATCHDOG_RESTART_SECONDS / 3600
        print(f"⏰ Watchdog: will restart after {restart_hours:.1f} hours uptime")
    
    if Config.WATCHDOG_MAX_CYCLES > 0:
        print(f"⏰ Watchdog: will restart after {Config.WATCHDOG_MAX_CYCLES} cycles")

    backoff_seconds = 120
    max_backoff = 900
    consecutive_failures = 0

    while True:
        cycle_start = time.time()
        success = False

        try:
            success = run_once()
        except Exception as e:
            print(f"❌ Unexpected error in run_once: {e}")
            traceback.print_exc()
            success = False

        # Cycle completed (cleanup already done in run_once finally block)
        cycle_count += 1
        elapsed = time.time() - cycle_start

        if success:
            # Reset backoff on success
            if consecutive_failures > 0:
                print(f"✅ Success after {consecutive_failures} failure(s), resetting backoff")
            consecutive_failures = 0
            backoff_seconds = 120
            
            # Use normal interval
            sleep_for = max(0, interval_seconds - elapsed)
            sleep_minutes = sleep_for / 60
            print(f"🕒 Sleeping {sleep_minutes:.1f} minutes (cycle took {int(elapsed)}s)")
        else:
            # Failure: use exponential backoff
            consecutive_failures += 1
            backoff_minutes = backoff_seconds / 60
            print(f"⚠️ Failure #{consecutive_failures}, backing off for {backoff_minutes:.1f} minutes")
            
            sleep_for = backoff_seconds
            
            # Double backoff for next failure, cap at max_backoff
            backoff_seconds = min(backoff_seconds * 2, max_backoff)

        # Check watchdog AFTER cycle completes and cleanup is done
        uptime = time.time() - start_time
        
        # Watchdog: restart by uptime
        if Config.WATCHDOG_RESTART_SECONDS > 0 and uptime >= Config.WATCHDOG_RESTART_SECONDS:
            uptime_hours = uptime / 3600
            print("=" * 60)
            print(f"🛑 Watchdog: restarting process after {uptime_hours:.2f} hours uptime")
            print(f"   Completed {cycle_count} cycles")
            print("=" * 60)
            os._exit(1)
        
        # Watchdog: restart by cycle count
        if Config.WATCHDOG_MAX_CYCLES > 0 and cycle_count >= Config.WATCHDOG_MAX_CYCLES:
            uptime_hours = uptime / 3600
            print("=" * 60)
            print(f"🛑 Watchdog: restarting process after {cycle_count} cycles")
            print(f"   Uptime: {uptime_hours:.2f} hours")
            print("=" * 60)
            os._exit(1)

        print("=" * 60 + "\n")
        time.sleep(sleep_for)


if __name__ == "__main__":
    if not validate_env():
        raise SystemExit(1)

    worker_loop(Config.CHECK_INTERVAL_SECONDS)

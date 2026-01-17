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

    PROJECTS_DB = os.getenv("PROJECTS_DB", "seen_projects.json")
    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))

    # If you ever want images enabled, set DISABLE_IMAGES=false
    DISABLE_IMAGES = os.getenv("DISABLE_IMAGES", "True").lower() == "true"


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
        with open(Config.PROJECTS_DB, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_seen_projects(projects):
    try:
        with open(Config.PROJECTS_DB, "w") as f:
            json.dump(projects, f, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to save projects: {e}")


def filter_new_projects(all_projects, seen_projects):
    seen_ids = {p.get("id") for p in seen_projects if p.get("id")}
    return [p for p in all_projects if p.get("id") and p["id"] not in seen_ids]


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
    # This selector was used in your Selenium version
    return page.locator(".need-card-inline-name").count() > 0

def perform_login(page) -> bool:
    try:
        page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Login form
        page.wait_for_selector('input[name="email"]', timeout=20000)
        page.fill('input[name="email"]', Config.CATALANT_EMAIL)
        page.fill('input[name="password"]', Config.CATALANT_PASSWORD)

        # Click submit (button text varies)
        # Try common patterns
        if page.locator('button:has-text("Login")').count() > 0:
            page.click('button:has-text("Login")')
        else:
            page.click('button[type="submit"]')

        # Wait for dashboard cards
        page.wait_for_selector(".need-card-inline-name", timeout=30000)
        print("✅ Login successful")
        return True
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False

def setup_session(context, page) -> bool:
    """
    Uses storage_state if present; otherwise logs in and saves storage_state.
    """
    try:
        page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        if is_logged_in(page):
            print("✅ Logged in via saved session (storage_state)")
            return True

        # Not logged in → perform login
        ok = perform_login(page)
        if ok:
            try:
                context.storage_state(path=Config.STORAGE_STATE_FILE)
                print(f"✅ Saved session state: {Config.STORAGE_STATE_FILE}")
            except Exception as e:
                print(f"⚠️ Could not save storage_state: {e}")
        return ok

    except Exception as e:
        print(f"❌ Session setup failed: {e}")
        return False

def extract_project_data_from_card(card) -> dict | None:
    try:
        # Title
        title = card.locator(".need-card-inline-name .line-clamp-2").first.inner_text().strip()
        if not title:
            return None

        # Project ID (from data-ajax-post)
        project_id = None
        like_btn = card.locator("[data-ajax-post*='need/']").first
        if like_btn.count() > 0:
            ajax = like_btn.get_attribute("data-ajax-post") or ""
            m = re.search(r"/need/([^/]+)/", ajax)
            if m:
                project_id = m.group(1)
        if not project_id:
            return None

        # Categories
        categories = []
        cat_loc = card.locator(".need-card-inline-pools .small.text-muted").first
        if cat_loc.count() > 0:
            cat_text = cat_loc.inner_text().strip()
            if cat_text:
                categories = [c.strip() for c in cat_text.split("|") if c.strip()]

        # Description
        description = ""
        desc_loc = card.locator(".need-card-inline-details .line-clamp-2").first
        if desc_loc.count() > 0:
            description = desc_loc.inner_text().strip()

        # Location
        location = ""
        loc_loc = card.locator(".text-gray-25.font-weight-semibold").first
        if loc_loc.count() > 0:
            location = (loc_loc.inner_text() or "").replace("Remote", "").strip()

        # Time posted
        time_posted = "Unknown"
        # similar xpath as selenium; use locator with text
        posted_loc = card.locator("span:has-text('Posted')").first
        if posted_loc.count() > 0:
            txt = posted_loc.inner_text().strip()
            time_posted = txt.replace("Posted", "").replace("ago", "").strip()

        # Status
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
        page.wait_for_selector(".need-card-inline-name", timeout=15000)

        # Similar to selenium: div.card-block which contains .need-card-inline
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


def run_once():
    print("=" * 60)
    print(f"🔄 Cycle started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

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

        if Config.DISABLE_IMAGES:
            context.route("**/*", _route_block_images)

        page = context.new_page()

        try:
            if not setup_session(context, page):
                print("❌ Failed to establish session")
                return

            seen_projects = load_seen_projects()
            print(f"📁 Loaded {len(seen_projects)} seen projects")

            all_projects = scan_for_projects(page)
            if not all_projects:
                print("⚠️ No projects found (or page didn't load)")
                return

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

        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            print("✅ Browser closed")


def worker_loop(interval_seconds: int):
    print("🟢 Worker started (Playwright)")
    print(f"⏱️ Interval: {interval_seconds}s")

    while True:
        start = time.time()

        try:
            run_once()
        except Exception as e:
            print(f"❌ Cycle crashed: {e}")
            traceback.print_exc()

        elapsed = time.time() - start
        sleep_for = max(0, interval_seconds - elapsed)
        print(f"🕒 Sleeping {int(sleep_for)}s (cycle took {int(elapsed)}s)")
        time.sleep(sleep_for)


if __name__ == "__main__":
    if not validate_env():
        raise SystemExit(1)

    worker_loop(Config.CHECK_INTERVAL_SECONDS)

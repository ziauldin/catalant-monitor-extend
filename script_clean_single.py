import time
import smtplib
import json
import os
import re
import traceback
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

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

    COOKIES_FILE = os.getenv("COOKIES_FILE", "catalant_cookies.json")
    PROJECTS_DB = os.getenv("PROJECTS_DB", "seen_projects.json")

    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))


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
# SESSION MANAGEMENT
# ============================

def save_cookies(driver):
    """Save session cookies to file"""
    try:
        with open(Config.COOKIES_FILE, "w") as f:
            json.dump(driver.get_cookies(), f)
        return True
    except Exception as e:
        print(f"⚠️ Could not save cookies: {e}")
        return False


def load_cookies(driver):
    """Load cookies from file"""
    if not os.path.exists(Config.COOKIES_FILE):
        return False

    try:
        with open(Config.COOKIES_FILE, "r") as f:
            cookies = json.load(f)

        driver.get("https://app.gocatalant.com")
        time.sleep(2)

        driver.delete_all_cookies()

        for cookie in cookies:
            if "domain" in cookie and ".gocatalant.com" in cookie["domain"]:
                driver.add_cookie(cookie)

        return True
    except Exception as e:
        print(f"⚠️ Could not load cookies: {e}")
        return False


def perform_login(driver):
    """Perform login to Catalant"""
    try:
        driver.get("https://app.gocatalant.com/c/_/u/0/dashboard/")
        time.sleep(3)

        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )

        driver.find_element(By.NAME, "email").send_keys(Config.CATALANT_EMAIL)
        driver.find_element(By.NAME, "password").send_keys(Config.CATALANT_PASSWORD)

        driver.find_element(
            By.XPATH, "//button[contains(text(), 'Login') or @type='submit']"
        ).click()

        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".need-card-inline-name"))
        )

        save_cookies(driver)
        print("✅ Login successful")
        return True

    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False


def setup_session(driver):
    """Setup browser session with cookies or login"""
    if load_cookies(driver):
        driver.get("https://app.gocatalant.com/c/_/u/0/dashboard/")
        time.sleep(5)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".need-card-inline-name"))
            )
            print("✅ Logged in via cookies")
            return True
        except Exception:
            pass

    return perform_login(driver)


# ============================
# PROJECT EXTRACTION
# ============================

def extract_project_data(card):
    """Extract data from a project card - returns None if invalid"""
    try:
        title_elem = card.find_element(By.CSS_SELECTOR, ".need-card-inline-name .line-clamp-2")
        title = title_elem.text.strip()
        if not title:
            return None

        # Project ID
        try:
            like_button = card.find_element(By.CSS_SELECTOR, "[data-ajax-post*='need/']")
            match = re.search(r"/need/([^/]+)/", like_button.get_attribute("data-ajax-post"))
            if not match:
                return None
            project_id = match.group(1)
        except Exception:
            return None

        categories = []
        try:
            cat_text = card.find_element(
                By.CSS_SELECTOR, ".need-card-inline-pools .small.text-muted"
            ).text.strip()
            categories = [c.strip() for c in cat_text.split("|") if c.strip()]
        except Exception:
            pass

        description = ""
        try:
            description = card.find_element(
                By.CSS_SELECTOR, ".need-card-inline-details .line-clamp-2"
            ).text.strip()
        except Exception:
            pass

        location = ""
        try:
            loc_text = card.find_element(By.CSS_SELECTOR, ".text-gray-25.font-weight-semibold").text
            location = loc_text.replace("Remote", "").strip()
        except Exception:
            pass

        time_posted = "Unknown"
        try:
            time_elems = card.find_elements(
                By.XPATH,
                ".//div[contains(@class, 'small') and contains(@class, 'text-gray-20') and contains(@class, 'mt-1')]//span[contains(text(), 'Posted')]"
            )
            if time_elems:
                time_posted = time_elems[0].text.replace("Posted", "").replace("ago", "").strip()
        except Exception:
            pass

        status = "Posted"
        try:
            card.find_element(By.CSS_SELECTOR, ".badge-success")
            status = "New Project"
        except Exception:
            pass

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


def scan_for_projects(driver):
    """Scan dashboard for project cards - returns only valid projects"""
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".need-card-inline-name"))
        )

        all_cards = driver.find_elements(By.CSS_SELECTOR, "div.card-block")
        project_cards = [c for c in all_cards if c.find_elements(By.CSS_SELECTOR, ".need-card-inline")]

        projects = []
        for card in project_cards:
            project = extract_project_data(card)
            if project and project.get("title") and project.get("id"):
                projects.append(project)

        print(f"✅ Extracted {len(projects)} valid projects")
        return projects

    except TimeoutException:
        print("⏳ Timeout waiting for projects")
        return []
    except Exception as e:
        print(f"❌ Error scanning: {e}")
        return []


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
# DRIVER INITIALIZATION
# ============================

def initialize_driver():
    """Initialize Chrome WebDriver with Railway/container support"""
    from selenium.webdriver.chrome.service import Service

    options = Options()

    # Headless mode for containers
    if Config.HEADLESS:
        options.add_argument("--headless=new")

    # Critical container flags - MUST HAVE for containerized Chrome
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--single-process")  # Important for containers with limited resources
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-debugging-port=9222")
    
    # Memory and stability options
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-breakpad")
    options.add_argument("--disable-component-extensions-with-background-pages")
    options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees")
    options.add_argument("--disable-ipc-flooding-protection")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
    options.add_argument("--force-color-profile=srgb")
    options.add_argument("--hide-scrollbars")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--mute-audio")
    
    # User agent
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    # Anti-detection
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Preferences
    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.images": 2  # Disable images to save bandwidth
    }
    options.add_experimental_option("prefs", prefs)

    # Try container paths first (for Docker/Railway), then webdriver-manager
    chromedriver_path = None
    for p in ["/usr/bin/chromedriver", "/usr/lib/chromium/chromedriver"]:
        if os.path.exists(p):
            chromedriver_path = p
            break
    
    if chromedriver_path:
        # Container environment
        print("✅ Using container chromedriver:", chromedriver_path)
        
        # Set Chromium binary if in container
        if os.path.exists("/usr/bin/chromium"):
            options.binary_location = "/usr/bin/chromium"
            print("✅ Chromium binary:", "/usr/bin/chromium")
        elif os.path.exists("/usr/bin/chromium-browser"):
            options.binary_location = "/usr/bin/chromium-browser"
            print("✅ Chromium binary:", "/usr/bin/chromium-browser")
            
        service = Service(executable_path=chromedriver_path)
    else:
        # Local environment - use webdriver-manager
        print("✅ Using webdriver-manager for chromedriver")
        service = Service(ChromeDriverManager().install())

    print("🚀 Initializing Chrome driver...")
    driver = webdriver.Chrome(service=service, options=options)
    print("✅ Chrome driver initialized successfully")
    
    # Anti-detection
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    return driver




# ============================
# SINGLE CYCLE
# ============================

def run_once():
    print("=" * 60)
    print(f"🔄 Cycle started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    driver = initialize_driver()

    try:
        if not setup_session(driver):
            print("❌ Failed to establish session")
            return

        seen_projects = load_seen_projects()
        print(f"📁 Loaded {len(seen_projects)} seen projects")

        all_projects = scan_for_projects(driver)
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
            driver.quit()
        except Exception:
            pass
        print("✅ Browser closed")


# ============================
# WORKER LOOP (every N seconds)
# ============================

def worker_loop(interval_seconds: int):
    print("🟢 Worker started")
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

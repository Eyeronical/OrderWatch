import os
import re
import io
import json
import time
import hmac
import uuid
import logging
import threading
from datetime import datetime, timezone, date, timedelta
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

SCRAPER_TZ = os.getenv("SCRAPER_TZ", "Asia/Kolkata")

try:
    import PyPDF2
    HAS_PYPDF2 = True
except Exception:
    HAS_PYPDF2 = False

try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
    HAS_PDFMINER = True
except Exception:
    HAS_PDFMINER = False

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
HEADLESS = os.getenv("HEADLESS", "1").lower() in ("1", "true", "yes")
PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", "90"))
SELENIUM_WAIT = int(os.getenv("SELENIUM_WAIT", "25"))
PDF_TIMEOUT = int(os.getenv("PDF_TIMEOUT", "45"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
MAX_PDF_BYTES = int(os.getenv("MAX_PDF_BYTES", str(15 * 1024 * 1024)))
API_KEY = os.getenv("API_KEY", "").strip()
MIN_DATE = date(2010, 1, 1)
JOB_TTL_MINUTES = int(os.getenv("JOB_TTL_MINUTES", "120"))
UA = os.getenv("SCRAPER_UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118 Safari/537.36")

CACHE_DIR = Path(os.getenv("CACHE_DIR", "data/cache"))
CACHE_TTL_MINUTES = int(os.getenv("CACHE_TTL_MINUTES", "1440"))
PDF_WORKERS = int(os.getenv("PDF_WORKERS", "4"))

USAGE_FILE = Path(os.getenv("USAGE_FILE", "data/analysis_runs.count"))

DATES_STORE_FILE = Path(os.getenv("DATES_STORE_FILE", "data/dates.index"))
BLOCK_HEAVY_RESOURCES = os.getenv("BLOCK_HEAVY_RESOURCES", "1").lower() in ("1", "true", "yes")

PDF_CACHE_TTL_MINUTES = int(os.getenv("PDF_CACHE_TTL_MINUTES", "10080"))
PDF_CACHE_MAX_ENTRIES = int(os.getenv("PDF_CACHE_MAX_ENTRIES", "256"))

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

_pdf_mem_cache: Dict[str, Tuple[datetime, List[Dict], str]] = {}
_pdf_mem_cache_ttl = timedelta(minutes=PDF_CACHE_TTL_MINUTES)
_pdf_cache_lock = threading.Lock()

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s")
logger = logging.getLogger("bse-scraper")

def _parse_origins(origins: str):
    if origins.strip() == "*":
        return "*"
    return [o.strip() for o in origins.split(",") if o.strip()]

app = Flask(__name__)
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": _parse_origins(ALLOWED_ORIGINS),
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "X-Requested-With", "X-API-Key", "Cache-Control", "Pragma", "Accept", "Origin"],
            "expose_headers": ["Retry-After"],
            "supports_credentials": False,
        }
    },
)

@app.after_request
def add_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0"
    return resp

def _require_api_key() -> bool:
    if not API_KEY:
        return True
    h = request.headers.get("X-API-Key", "")
    qs = request.args.get("api_key", "")
    key = h or qs
    return bool(key) and hmac.compare_digest(key, API_KEY)

_analysis_runs_lock = threading.Lock()

def _ensure_analysis_runs_file():
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not USAGE_FILE.exists():
            USAGE_FILE.write_text("0")
    except Exception as e:
        logger.warning(f"Could not prepare analysis runs file: {e}")

def _read_analysis_runs():
    try:
        return int(USAGE_FILE.read_text().strip())
    except Exception:
        return 0

def _write_analysis_runs(v: int):
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(str(v))
    except Exception as e:
        logger.warning(f"Could not write analysis runs file: {e}")

def _increment_analysis_runs():
    with _analysis_runs_lock:
        current = _read_analysis_runs()
        new_count = current + 1
        _write_analysis_runs(new_count)
        return new_count

_ensure_analysis_runs_file()

@app.route("/api/usage", methods=["GET"])
def usage_get():
    return jsonify({
        "analysis_runs": _read_analysis_runs(),
        "total_usage": _read_analysis_runs()
    }), 200

@app.route("/api/visit", methods=["GET"])
def visit_get():
    return jsonify({
        "visits": _read_analysis_runs(),
        "analysis_runs": _read_analysis_runs()
    }), 200

_dates_index_lock = threading.Lock()

def _now_in_config_tz() -> datetime:
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(SCRAPER_TZ))
        except Exception:
            pass
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))

def is_today_formatted(formatted_date: str) -> bool:
    try:
        return formatted_date == _now_in_config_tz().date().strftime("%d/%m/%Y")
    except Exception:
        return False

def _dates_index_load() -> set:
    try:
        if not DATES_STORE_FILE.exists():
            return set()
        return {line.strip() for line in DATES_STORE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}
    except Exception:
        return set()

def _dates_index_add(formatted_date: str):
    try:
        with _dates_index_lock:
            DATES_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
            existing = _dates_index_load()
            if formatted_date not in existing:
                with DATES_STORE_FILE.open("a", encoding="utf-8") as f:
                    f.write(formatted_date + "\n")
    except Exception as e:
        logger.debug(f"Failed to update date index: {e}")

def _pdf_cache_get(url: str) -> Optional[Tuple[List[Dict], str]]:
    now = datetime.now(timezone.utc)
    with _pdf_cache_lock:
        entry = _pdf_mem_cache.get(url)
        if not entry:
            return None
        ts, values, snippet = entry
        if now - ts > _pdf_mem_cache_ttl:
            _pdf_mem_cache.pop(url, None)
            return None
        return values, snippet

def _pdf_cache_put(url: str, values: List[Dict], snippet: str):
    now = datetime.now(timezone.utc)
    with _pdf_cache_lock:
        _pdf_mem_cache[url] = (now, values, snippet)
        if len(_pdf_mem_cache) > PDF_CACHE_MAX_ENTRIES:
            items = sorted(_pdf_mem_cache.items(), key=lambda kv: kv[1])
            to_drop = len(_pdf_mem_cache) - PDF_CACHE_MAX_ENTRIES
            for i in range(to_drop):
                _pdf_mem_cache.pop(items[i][0], None)

def setup_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.page_load_strategy = "eager"
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--hide-scrollbars")
    opts.add_argument("--mute-audio")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={UA}")
    opts.add_argument("--remote-debugging-pipe")
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.plugins": 2,
    }
    opts.add_experimental_option("prefs", prefs)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=opts)
    try:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception:
        pass

    if BLOCK_HEAVY_RESOURCES:
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setBlockedURLs", {
                "urls": [
                    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.ico",
                    "*.mp4", "*.webm", "*.avi",
                    "*.woff", "*.woff2", "*.ttf", "*.otf", "*.eot", "*.svg"
                ]
            })
        except Exception as e:
            logger.debug(f"CDP block setup failed: {e}")

    return driver

def _wait_until_css(driver: webdriver.Chrome, css: str):
    while True:
        try:
            if driver.find_elements(By.CSS_SELECTOR, css):
                return
        except Exception:
            pass
        time.sleep(0.25)

def safe_get(driver: webdriver.Chrome, url: str, wait_css: str = "body"):
    try:
        driver.get(url)
    except Exception:
        pass
    _wait_until_css(driver, wait_css)

def validate_date(date_str: str) -> Tuple[str, datetime]:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid date format. Expected YYYY-MM-DD")
    d_only = dt.date()
    if d_only > _now_in_config_tz().date():
        raise ValueError("Date cannot be in the future")
    if d_only < MIN_DATE:
        raise ValueError("Date cannot be before 2010-01-01")
    return dt.strftime("%d/%m/%Y"), dt

def set_date_field(driver: webdriver.Chrome, field_id: str, date_value: str, label: str) -> bool:
    try:
        while True:
            els = driver.find_elements(By.ID, field_id)
            if els:
                el = els[0]
                break
            time.sleep(0.2)
        driver.execute_script("arguments[0].removeAttribute('readonly');", el)
        driver.execute_script("arguments[0].value='';", el)
        driver.execute_script("arguments[0].value=arguments[1];", el, date_value)
        driver.execute_script("""
            const e = arguments[0];
            for (const ev of ['input','change','blur']) {
              e.dispatchEvent(new Event(ev, {bubbles: true}));
            }
        """, el)
        time.sleep(0.5)
        return True
    except Exception as e:
        logger.warning(f"Failed to set {label}: {e}")
        return False

def accept_cookies_if_any(driver):
    try:
        xpaths = [
            "//*[@id='onetrust-accept-btn-handler']",
            "//*[@id='acceptCookie']",
            "//button[contains(.,'Accept')]",
            "//a[contains(.,'Accept')]",
        ]
        for xp in xpaths:
            els = driver.find_elements(By.XPATH, xp)
            if els:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", els[0])
                time.sleep(0.2)
                driver.execute_script("arguments[0].click();", els[0])
                time.sleep(0.3)
                return True
    except Exception:
        pass
    return False

def submit_form(driver: webdriver.Chrome) -> bool:
    try:
        candidates = [
            (By.CSS_SELECTOR, "#btnSubmit"),
            (By.CSS_SELECTOR, "#btnsubmit"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.CSS_SELECTOR, "input[type='button'][value='Search']"),
            (By.CSS_SELECTOR, "button#btnSearch"),
            (By.XPATH, "//button[contains(.,'Search')]"),
            (By.XPATH, "//input[@value='Search']"),
        ]
        button = None
        for by, sel in candidates:
            els = driver.find_elements(by, sel)
            if els:
                button = els[0]
                break

        if button:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
            time.sleep(0.2)
            try:
                driver.execute_script("arguments[0].disabled=false;", button)
            except Exception:
                pass
            driver.execute_script("""
                const el = arguments[0];
                ['mouseover','mousedown','mouseup','click'].forEach(ev =>
                  el.dispatchEvent(new MouseEvent(ev, {bubbles:true, cancelable:true}))
                );
            """, button)
            time.sleep(0.8)
            return True

        try:
            to_els = driver.find_elements(By.ID, "txtToDt")
            if to_els:
                to_els[0].send_keys(Keys.ENTER)
                time.sleep(0.8)
                return True
        except Exception:
            pass

        return False
    except Exception as e:
        logger.error(f"Error submitting form: {e}")
        return False

def wait_for_results_or_empty(driver: webdriver.Chrome) -> bool:
    while True:
        try:
            if driver.find_elements(By.CSS_SELECTOR, 'table[ng-repeat="cann in CorpannData.Table"]'):
                return True
            src = (driver.page_source or "").lower()
            if "no record" in src or "no records" in src:
                return True
        except Exception:
            pass
        time.sleep(0.3)

def get_total_announcements(driver: webdriver.Chrome) -> int:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, ".col-lg-6.text-right.ng-binding b.ng-binding")
        if els:
            txt = els[0].text.strip()
            nums = re.findall(r"\d+", txt)
            if nums:
                return int(nums[0])
    except Exception:
        pass
    try:
        els = driver.find_elements(By.CSS_SELECTOR, ".col-lg-6.text-right, .col-lg-6.text-right.ng-binding")
        txt = " ".join([e.text.strip() for e in els if e.text.strip()])
        nums = re.findall(r"\d+", txt)
        if nums:
            return int(nums[-1])
    except Exception:
        pass
    return 0

def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    return s

ORDER_KEYWORDS = [
    "award of order",
    "receipt of order",
    "order received",
    "order bagged",
    "bagged order",
    "purchase order",
    "po received",
    "contract awarded",
    "work order",
    "letter of award",
    "loi",
]

def is_order_announcement(title: str, summary: str = "") -> bool:
    hay = normalize_text(title) + " || " + normalize_text(summary)
    if "announcement under regulation 30" in hay and ("award of order" in hay or "receipt of order" in hay):
        return True
    return any(k in hay for k in ORDER_KEYWORDS)

def clean_company_name(company: str, title: str) -> str:
    name = (company or "").strip()
    if not name and title:
        parts = title.split(" - ")
        if parts:
            name = parts[0].strip()
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    return name.title() if name else ""

def scrape_announcement_tables_on_page(driver: webdriver.Chrome, page_num: int, sink: List[Dict], stop_event: threading.Event) -> int:
    try:
        _wait_until_css(driver, 'table[ng-repeat="cann in CorpannData.Table"]')
    except Exception:
        return 0

    tables = driver.find_elements(By.CSS_SELECTOR, 'table[ng-repeat="cann in CorpannData.Table"]')
    count = 0
    for idx, table in enumerate(tables, 1):
        if stop_event.is_set():
            break
        try:
            rows = table.find_elements(By.TAG_NAME, "tr")
            first_cells = rows[0].find_elements(By.TAG_NAME, "td") if rows else []
            company = first_cells[0].text.strip() if first_cells else ""

            title = ""
            try:
                title_span = table.find_element(By.CSS_SELECTOR, "span[ng-bind-html='cann.NEWSSUB']")
                title = title_span.text.strip()
            except Exception:
                if first_cells and len(first_cells) > 1:
                    title = first_cells[1].text.strip()
                if not title:
                    for sp in table.find_elements(By.TAG_NAME, "span"):
                        t = sp.text.strip()
                        if "Announcement under Regulation 30" in t or "Order" in t or "Contract" in t:
                            title = t
                            break

            summary = ""
            try:
                for r in rows[1:]:
                    txt = r.text.strip()
                    if txt and txt != title and len(txt) > 10:
                        summary = txt
                        break
            except Exception:
                pass

            if not is_order_announcement(title, summary):
                continue

            pdf_link = None
            try:
                for a in table.find_elements(By.TAG_NAME, "a"):
                    href = (a.get_attribute("href") or "").strip()
                    if ".pdf" in href.lower() or "download" in href.lower():
                        pdf_link = ("https://www.bseindia.com" + href) if href.startswith("/") else href
                        break
            except Exception:
                pass

            sink.append({
                "page": page_num,
                "announcement_num": idx,
                "company": clean_company_name(company, title),
                "raw_company": company,
                "title": title,
                "summary": summary or "No summary available",
                "pdf_link": pdf_link or "No PDF available",
                "order_values": [],
                "total_value_crores": 0.0,
                "pdf_extract": "Not parsed",
            })
            count += 1
        except Exception as e:
            logger.debug(f"Error processing announcement {idx}: {e}")
            continue
    return count

def click_next_if_available(driver: webdriver.Chrome) -> bool:
    candidates = [
        (By.ID, "idnext"),
        (By.CSS_SELECTOR, "#idnext"),
        (By.XPATH, "//a[contains(.,'Next')]"),
        (By.CSS_SELECTOR, "button.next, a.next"),
    ]
    for by, sel in candidates:
        try:
            els = driver.find_elements(by, sel)
            if not els:
                continue
            next_btn = els[0]
            if not next_btn.is_displayed():
                continue
            cls = (next_btn.get_attribute("class") or "").lower()
            if "disabled" in cls or "ng-hide" in cls:
                continue
            driver.execute_script("arguments[0].click();", next_btn)
            time.sleep(1.0)
            return True
        except Exception:
            continue
    return False

def handle_pagination_and_scrape(driver: webdriver.Chrome, stop_event: threading.Event) -> List[Dict]:
    page_num = 1
    orders: List[Dict] = []
    while True:
        if stop_event.is_set():
            break
        scrape_announcement_tables_on_page(driver, page_num, orders, stop_event)
        if stop_event.is_set():
            break
        moved = click_next_if_available(driver)
        if not moved:
            break
        time.sleep(0.5)
        page_num += 1
    return orders

def _is_allowed_pdf_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        host = parsed.hostname or ""
        return host.endswith("bseindia.com")
    except Exception:
        return False

def extract_pdf_text(content: bytes) -> str:
    if HAS_PYPDF2:
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(content))
            out = []
            for page in reader.pages:
                try:
                    out.append(page.extract_text() or "")
                except Exception:
                    continue
            if out:
                return "\n".join(out)
        except Exception as e:
            logger.debug(f"PyPDF2 failed: {e}")
    if HAS_PDFMINER:
        try:
            with io.BytesIO(content) as buf:
                return pdfminer_extract_text(buf) or ""
        except Exception as e:
            logger.debug(f"pdfminer failed: {e}")
    return ""

def extract_order_value_from_text(text: str) -> List[Dict]:
    patterns = [
        r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|crores|cr)\b",
        r"([\d,]+(?:\.\d+)?)\s*(crore|crores|cr)\b",
        r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lakhs)\b",
        r"([\d,]+(?:\.\d+)?)\s*(lakh|lakhs)\b",
        r"([\d,]+(?:\.\d+)?)\s*(million|mn|m)\b",
        r"([\d,]+(?:\.\d+)?)\s*(billion|bn|b)\b",
        r"(?:worth|value|amount)\s*(?:of\s*)?(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(crore|crores|cr|lakh|lakhs|million|mn|m|billion|bn|b)\b",
        r"(?:contract|order)\s*(?:worth|value|amount)?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(crore|crores|cr|lakh|lakhs|million|mn|m|billion|bn|b)\b",
    ]
    def to_float(s: str) -> float:
        return float(s.replace(",", ""))
    def to_crores(value: float, unit: str) -> float:
        u = unit.lower()
        if u in ("crore", "crores", "cr"):
            return value
        if u in ("lakh", "lakhs"):
            return value * 0.01
        if u in ("million", "mn", "m"):
            return value / 10.0
        if u in ("billion", "bn", "b"):
            return value * 100.0
        return 0.0

    found = []
    lower = (text or "").lower()
    for pat in patterns:
        for m in re.finditer(pat, lower, re.IGNORECASE):
            try:
                value = to_float(m.group(1))
                unit = m.group(2)
                crores = to_crores(value, unit)
                if crores <= 0:
                    continue
                found.append({
                    "value": value,
                    "unit": unit.lower(),
                    "formatted": f"₹{value:,.2f} {unit}",
                    "value_in_crores": round(crores, 4),
                })
            except Exception:
                continue
    dedup = []
    seen = set()
    for item in found:
        key = (round(item["value"], 4), item["unit"])
        if key not in seen:
            seen.add(key)
            dedup.append(item)
    return dedup

def fetch_pdf_and_extract_values(pdf_url: str) -> Tuple[List[Dict], str]:
    if not _is_allowed_pdf_url(pdf_url):
        return [], "PDF URL not allowed"

    cached = _pdf_cache_get(pdf_url)
    if cached:
        values, snippet = cached
        return values, snippet

    try:
        headers = {"User-Agent": UA}
        try:
            head = SESSION.head(pdf_url, headers=headers, allow_redirects=True)
            clen = int(head.headers.get("Content-Length", "0")) if head.ok else 0
            if clen and clen > MAX_PDF_BYTES:
                return [], "PDF too large to process"
        except Exception:
            pass

        r = SESSION.get(pdf_url, headers=headers)
        r.raise_for_status()
        if len(r.content) > MAX_PDF_BYTES:
            return [], "PDF too large to process"

        text = extract_pdf_text(r.content)
        values = extract_order_value_from_text(text)
        snippet = (text or "")[:500] or "No text extracted from PDF"

        _pdf_cache_put(pdf_url, values, snippet)
        return values, snippet
    except Exception as e:
        logger.warning(f"PDF extraction failed: {str(e)[:120]}")
        return [], "PDF extraction failed"

def enrich_orders_with_pdfs(orders: List[Dict]):
    def work(idx, url):
        try:
            values, snippet = fetch_pdf_and_extract_values(url)
        except Exception:
            values, snippet = [], "PDF extraction failed"
        total_crores = round(sum(v.get("value_in_crores", 0) for v in values), 2)
        return idx, values, total_crores, (snippet or "")[:500]

    futures = {}
    with ThreadPoolExecutor(max_workers=PDF_WORKERS) as ex:
        for i, o in enumerate(orders):
            url = o.get("pdf_link")
            if url and url != "No PDF available" and _is_allowed_pdf_url(url):
                futures[ex.submit(work, i, url)] = i
        for fut in as_completed(futures):
            idx, values, total, snippet = fut.result()
            orders[idx]["order_values"] = values
            orders[idx]["total_value_crores"] = total
            orders[idx]["pdf_extract"] = snippet

def dedupe_orders(orders: List[Dict]) -> List[Dict]:
    seen = set()
    unique = []
    for o in orders:
        key = (
            (o.get("company") or "").strip().lower(),
            (o.get("title") or "").strip().lower(),
            (o.get("pdf_link") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(o)
    return unique

_mem_cache: Dict[str, Tuple[datetime, Dict]] = {}
_mem_cache_ttl = timedelta(minutes=CACHE_TTL_MINUTES)

def _cache_path(formatted_date: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = formatted_date.replace("/", "-")
    return CACHE_DIR / f"{safe}.json"

def cache_load(formatted_date: str) -> Optional[Dict]:
    if is_today_formatted(formatted_date):
        return None

    now = datetime.now(timezone.utc)
    entry = _mem_cache.get(formatted_date)
    if entry:
        ts, data = entry
        if now - ts <= _mem_cache_ttl:
            return data
        else:
            _mem_cache.pop(formatted_date, None)

    path = _cache_path(formatted_date)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        _mem_cache[formatted_date] = (now, data)
        return data
    except Exception as e:
        logger.debug(f"Cache load failed for {formatted_date}: {e}")
        return None

def cache_save(formatted_date: str, data: Dict):
    try:
        now = datetime.now(timezone.utc)
        _mem_cache[formatted_date] = (now, data)
        path = _cache_path(formatted_date)
        tmp = path.with_suffix(".json.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        _dates_index_add(formatted_date)
    except Exception as e:
        logger.debug(f"Cache save failed for {formatted_date}: {e}")

class ScrapeJob:
    def __init__(self, job_id: str, formatted_date: str):
        self.job_id = job_id
        self.formatted_date = formatted_date
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.status = {
            "job_id": job_id,
            "is_running": False,
            "progress": 0,
            "message": "",
            "results": None,
            "error": None,
            "total_announcements": 0,
            "started_at": None,
            "finished_at": None,
        }

    def update(self, **kwargs):
        with self.lock:
            self.status.update(kwargs)

    def get_status(self):
        with self.lock:
            return dict(self.status)

    def start(self):
        self.thread = threading.Thread(target=self.run, name=f"scraper-{self.job_id[:8]}", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.update(message="Stop requested")

    def run(self):
        driver = None
        try:
            cached = cache_load(self.formatted_date)
            if cached:
                now_iso = datetime.now(timezone.utc).isoformat()
                self.update(
                    is_running=False,
                    progress=100,
                    message="Served from cache",
                    results=cached,
                    error=None,
                    started_at=now_iso,
                    finished_at=now_iso,
                )
                return

            self.update(is_running=True, progress=10, message="Setting up browser...", started_at=datetime.now(timezone.utc).isoformat())
            driver = setup_driver(headless=HEADLESS)

            self.update(progress=20, message="Opening BSE announcements page...")
            safe_get(driver, "https://www.bseindia.com/corporates/ann.html", wait_css="body")
            accept_cookies_if_any(driver)
            time.sleep(0.5)
            if self.stop_event.is_set():
                raise InterruptedError("Stopped by user")

            self.update(progress=30, message=f"Setting date to {self.formatted_date}...")
            from_ok = set_date_field(driver, "txtFromDt", self.formatted_date, "From Date")
            to_ok = set_date_field(driver, "txtToDt", self.formatted_date, "To Date")
            if not (from_ok and to_ok):
                logger.warning("Date fields may not have been set correctly, continuing...")

            self.update(progress=40, message="Submitting form...")
            if not submit_form(driver):
                raise RuntimeError("Failed to submit form")

            self.update(progress=50, message="Waiting for results...")
            wait_for_results_or_empty(driver)

            total_announcements = get_total_announcements(driver)
            self.update(total_announcements=total_announcements)

            self.update(progress=60, message="Scanning announcements for order wins...")
            orders = handle_pagination_and_scrape(driver, stop_event=self.stop_event)
            if self.stop_event.is_set():
                raise InterruptedError("Stopped by user")

            orders = dedupe_orders(orders)

            if orders:
                self.update(progress=75, message="Analyzing PDFs for order values...")
                enrich_orders_with_pdfs(orders)

            if orders:
                orders.sort(key=lambda x: x.get("total_value_crores", 0), reverse=True)
                total_value = round(sum(o.get("total_value_crores", 0) for o in orders), 2)
                results = {
                    "success": True,
                    "date": self.formatted_date,
                    "total_awards": len(orders),
                    "total_value_crores": total_value,
                    "total_announcements": total_announcements,
                    "orders": orders,
                    "statistics": {
                        "high_value_count": sum(1 for o in orders if o.get("total_value_crores", 0) >= 100),
                        "medium_value_count": sum(1 for o in orders if 10 <= o.get("total_value_crores", 0) < 100),
                        "low_value_count": sum(1 for o in orders if 0 < o.get("total_value_crores", 0) < 10),
                        "no_value_count": sum(1 for o in orders if o.get("total_value_crores", 0) == 0),
                    },
                }
            else:
                results = {
                    "success": True,
                    "date": self.formatted_date,
                    "total_awards": 0,
                    "total_value_crores": 0,
                    "total_announcements": total_announcements,
                    "orders": [],
                    "message": "No order awards found for this date",
                }

            cache_save(self.formatted_date, results)
            self.update(
                is_running=False,
                progress=100,
                message="Scraping completed",
                results=results,
                error=None,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except InterruptedError as ie:
            logger.info(f"[{self.job_id}] Scraper stopped: {ie}")
            self.update(
                is_running=False,
                progress=0,
                message="Scraping stopped by user",
                error=str(ie),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.exception(f"[{self.job_id}] Scraping failed")
            self.update(
                is_running=False,
                progress=0,
                message="Scraping failed",
                results=None,
                error=str(e),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass

class MultiScrapeManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: Dict[str, ScrapeJob] = {}

    def _cleanup(self):
        return

    def start(self, formatted_date: str) -> str:
        with self.lock:
            for jid, job in self.jobs.items():
                st = job.get_status()
                if job.formatted_date == formatted_date and st.get("is_running"):
                    return jid
            job_id = uuid.uuid4().hex
            job = ScrapeJob(job_id, formatted_date)
            self.jobs[job_id] = job
        job.start()
        self._cleanup()
        return job_id

    def get(self, job_id: str) -> Optional[ScrapeJob]:
        with self.lock:
            return self.jobs.get(job_id)

    def status(self, job_id: str):
        job = self.get(job_id)
        if not job:
            return None
        return job.get_status()

    def results(self, job_id: str):
        job = self.get(job_id)
        if not job:
            return None
        st = job.get_status()
        return st.get("results")

    def stop(self, job_id: str):
        job = self.get(job_id)
        if not job:
            return False
        job.stop()
        return True

scrape_manager = MultiScrapeManager()

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy",
        "message": "BSE Scraper API is running",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

@app.route("/api/scrape", methods=["POST"])
def start_scrape():
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400
    if not payload or "date" not in payload:
        return jsonify({"error": "Date is required in format YYYY-MM-DD"}), 400
    try:
        formatted_date, date_obj = validate_date(payload["date"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    analysis_count = _increment_analysis_runs()
    logger.info(f"Analysis run #{analysis_count} started for date: {formatted_date}")

    try:
        if not is_today_formatted(formatted_date):
            existing_dates = _dates_index_load()
            if formatted_date in existing_dates:
                cached = cache_load(formatted_date)
                if cached:
                    job_id = uuid.uuid4().hex
                    job = ScrapeJob(job_id, formatted_date)
                    now_iso = datetime.now(timezone.utc).isoformat()
                    job.update(
                        is_running=False,
                        progress=100,
                        message="Served from cache (index hit)",
                        results=cached,
                        error=None,
                        started_at=now_iso,
                        finished_at=now_iso,
                    )
                    with scrape_manager.lock:
                        scrape_manager.jobs[job_id] = job
                    return jsonify({
                        "message": "Scraping started (cache hit via index)",
                        "date": formatted_date,
                        "readable_date": date_obj.strftime("%B %d, %Y"),
                        "job_id": job_id,
                        "analysis_run_number": analysis_count
                    }), 202
    except Exception:
        pass

    cached = cache_load(formatted_date)
    if cached:
        job_id = uuid.uuid4().hex
        job = ScrapeJob(job_id, formatted_date)
        now_iso = datetime.now(timezone.utc).isoformat()
        job.update(
            is_running=False,
            progress=100,
            message="Served from cache",
            results=cached,
            error=None,
            started_at=now_iso,
            finished_at=now_iso,
        )
        with scrape_manager.lock:
            scrape_manager.jobs[job_id] = job
        return jsonify({
            "message": "Scraping started (cache hit)",
            "date": formatted_date,
            "readable_date": date_obj.strftime("%B %d, %Y"),
            "job_id": job_id,
            "analysis_run_number": analysis_count
        }), 202

    try:
        job_id = scrape_manager.start(formatted_date)
    except Exception:
        logger.exception("Failed to start scraper")
        return jsonify({"error": "Failed to start scraping"}), 500

    return jsonify({
        "message": "Scraping started",
        "date": formatted_date,
        "readable_date": date_obj.strftime("%B %d, %Y"),
        "job_id": job_id,
        "analysis_run_number": analysis_count
    }), 202

@app.route("/api/status", methods=["GET"])
def get_status():
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    job_id = request.args.get("job_id", "").strip()
    if not job_id:
        return jsonify({"error": "job_id is required"}), 400
    st = scrape_manager.status(job_id)
    if not st:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(st), 200

@app.route("/api/results", methods=["GET"])
def get_results():
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    job_id = request.args.get("job_id", "").strip()
    if not job_id:
        return jsonify({"error": "job_id is required"}), 400
    res = scrape_manager.results(job_id)
    st = scrape_manager.status(job_id)
    if res:
        return jsonify(res), 200
    if st and st.get("error"):
        return jsonify({"error": st["error"]}), 500
    if st and st.get("is_running"):
        return jsonify({"message": "Scraping is in progress"}), 202
    return jsonify({"message": "No results available"}), 404

@app.route("/api/stop", methods=["POST"])
def stop_scraping():
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}
    job_id = (payload.get("job_id") or request.args.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"error": "job_id is required"}), 400
    ok = scrape_manager.stop(job_id)
    if not ok:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"message": "Stop requested", "job_id": job_id}), 202

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.exception("Unhandled server error")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")), debug=False)
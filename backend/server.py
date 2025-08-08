import os
import re
import io
import time
import logging
import threading
import hmac
from datetime import datetime, timezone, date
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlparse
from pathlib import Path

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

try:
    import PyPDF2
    HAS_PYPDF2 = True
except Exception:
    HAS_PYPDF2 = False

# pdfminer import
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
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118 Safari/537.36"
MIN_DATE = date(2010, 1, 1)

def _parse_origins(origins: str):
    if origins.strip() == "*":
        return "*"
    return [o.strip() for o in origins.split(",") if o.strip()]

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s")
logger = logging.getLogger("bse-scraper")

app = Flask(__name__)
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": _parse_origins(ALLOWED_ORIGINS),
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": [
                "Content-Type",
                "X-Requested-With",
                "X-API-Key",
                "Cache-Control",
                "Pragma",
                "Accept",
                "Origin"
            ],
            "expose_headers": ["Retry-After"],
            "supports_credentials": False
        }
    }
)

@app.after_request
def add_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0"
    return resp

def _require_api_key():
    if not API_KEY:
        return True
    h = request.headers.get("X-API-Key", "")
    try_qs = request.args.get("api_key", "")
    key = h or try_qs
    return bool(key) and hmac.compare_digest(key, API_KEY)

class ScrapeManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._status = {
            "is_running": False,
            "progress": 0,
            "message": "",
            "results": None,
            "error": None,
            "total_announcements": 0,
            "started_at": None,
            "finished_at": None,
        }
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def get_status(self):
        with self._lock:
            return dict(self._status)

    def get_results(self):
        with self._lock:
            return self._status.get("results")

    def update_status(self, **kwargs):
        with self._lock:
            self._status.update(kwargs)

    def start(self, bse_formatted_date: str):
        with self._lock:
            if self._status["is_running"]:
                raise RuntimeError("A scraping job is already running")
            self._status.update(
                {
                    "is_running": True,
                    "progress": 0,
                    "message": "Starting...",
                    "results": None,
                    "error": None,
                    "total_announcements": 0,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": None,
                }
            )
            self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, args=(bse_formatted_date,), daemon=True, name="scraper-thread")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        with self._lock:
            self._status["message"] = "Stop requested"

    def _run(self, formatted_date: str):
        driver = None
        try:
            self.update_status(progress=10, message="Setting up browser...")
            driver = setup_driver(headless=HEADLESS)
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            self.update_status(progress=20, message="Opening BSE announcements page...")
            safe_get(driver, "https://www.bseindia.com/corporates/ann.html", wait_css="body")
            time.sleep(1)
            if self._stop_event.is_set():
                raise InterruptedError("Stopped by user")
            self.update_status(progress=30, message=f"Setting date to {formatted_date}...")
            from_ok = set_date_field(driver, "txtFromDt", formatted_date, "From Date")
            to_ok = set_date_field(driver, "txtToDt", formatted_date, "To Date")
            if not (from_ok and to_ok):
                logger.warning("Date fields may not have been set correctly, continuing...")
            self.update_status(progress=40, message="Submitting form...")
            if not submit_form(driver):
                raise RuntimeError("Failed to submit form")
            self.update_status(progress=50, message="Waiting for results...")
            WebDriverWait(driver, SELENIUM_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table[ng-repeat='cann in CorpannData.Table']"))
            )
            total_announcements = get_total_announcements(driver)
            self.update_status(total_announcements=total_announcements)
            self.update_status(progress=60, message="Scanning announcements for order wins...")
            orders = handle_pagination_and_scrape(driver, stop_event=self._stop_event)
            if self._stop_event.is_set():
                raise InterruptedError("Stopped by user")

            orders = dedupe_orders(orders)  # ensure counts match UI list

            if orders:
                orders.sort(key=lambda x: x.get("total_value_crores", 0), reverse=True)
                total_value = round(sum(o.get("total_value_crores", 0) for o in orders), 2)
                results = {
                    "success": True,
                    "date": formatted_date,
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
                    "date": formatted_date,
                    "total_awards": 0,
                    "total_value_crores": 0,
                    "total_announcements": total_announcements,
                    "orders": [],
                    "message": "No order awards found for this date",
                }
            self.update_status(
                is_running=False,
                progress=100,
                message="Scraping completed",
                results=results,
                error=None,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except InterruptedError as ie:
            logger.info(f"Scraper stopped: {ie}")
            self.update_status(
                is_running=False,
                progress=0,
                message="Scraping stopped by user",
                error=str(ie),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.exception("Scraping failed")
            self.update_status(
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

scrape_manager = ScrapeManager()

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
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=opts)
    try:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception:
        pass
    driver.set_script_timeout(60)
    return driver

def safe_get(driver: webdriver.Chrome, url: str, wait_css: str = "body", wait_timeout: int = SELENIUM_WAIT):
    try:
        driver.get(url)
    except TimeoutException:
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
    WebDriverWait(driver, wait_timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, wait_css)))

def validate_date(date_str: str) -> Tuple[str, datetime]:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid date format. Expected YYYY-MM-DD")
    d_only = dt.date()
    if d_only > date.today():
        raise ValueError("Date cannot be in the future")
    if d_only < MIN_DATE:
        raise ValueError("Date cannot be before 2010-01-01")
    return dt.strftime("%d/%m/%Y"), dt

def set_date_field(driver: webdriver.Chrome, field_id: str, date_value: str, label: str) -> bool:
    try:
        el = WebDriverWait(driver, SELENIUM_WAIT).until(EC.presence_of_element_located((By.ID, field_id)))
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

def submit_form(driver: webdriver.Chrome) -> bool:
    try:
        btn = WebDriverWait(driver, SELENIUM_WAIT).until(EC.element_to_be_clickable((By.ID, "btnSubmit")))
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)
        return True
    except Exception as e:
        logger.error(f"Error submitting form: {e}")
        return False

def get_total_announcements(driver: webdriver.Chrome) -> int:
    try:
        el = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".col-lg-6.text-right.ng-binding b.ng-binding"))
        )
        txt = el.text.strip()
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

def _is_allowed_pdf_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        host = parsed.hostname or ""
        if host.endswith("bseindia.com"):
            return True
        return False
    except Exception:
        return False

def fetch_pdf_and_extract_values(pdf_url: str) -> Tuple[List[Dict], str]:
    if not _is_allowed_pdf_url(pdf_url):
        return [], "PDF URL not allowed"
    try:
        headers = {"User-Agent": UA}
        head = requests.head(pdf_url, headers=headers, timeout=PDF_TIMEOUT, allow_redirects=True)
        clen = int(head.headers.get("Content-Length", "0")) if head.ok else 0
        if clen and clen > MAX_PDF_BYTES:
            return [], "PDF too large to process"
        r = requests.get(pdf_url, headers=headers, timeout=PDF_TIMEOUT)
        r.raise_for_status()
        if len(r.content) > MAX_PDF_BYTES:
            return [], "PDF too large to process"
        text = extract_pdf_text(r.content)
        values = extract_order_value_from_text(text)
        snippet = (text or "")[:500]
        return values, snippet if snippet else "No text extracted from PDF"
    except Exception as e:
        logger.warning(f"PDF extraction failed: {str(e)[:120]}")
        return [], "PDF extraction failed"

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
                found.append(
                    {
                        "value": value,
                        "unit": unit.lower(),
                        "formatted": f"₹{value:,.2f} {unit}",
                        "value_in_crores": round(crores, 4),
                    }
                )
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

def clean_company_name(company: str, title: str) -> str:
    name = (company or "").strip()
    if not name and title:
        parts = title.split(" - ")
        if parts:
            name = parts[0].strip()
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    return name.title() if name else ""

def dedupe_orders(orders: List[Dict]) -> List[Dict]:
    seen = set()
    unique = []
    for o in orders:
        key = (
            (o.get("company") or "").strip().lower(),
            (o.get("title") or "").strip().lower(),
            (o.get("pdf_link") or "").strip().lower()
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(o)
    return unique

def scrape_announcement_tables_on_page(driver: webdriver.Chrome, page_num: int, sink: List[Dict], stop_event: threading.Event) -> int:
    try:
        WebDriverWait(driver, SELENIUM_WAIT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table[ng-repeat='cann in CorpannData.Table']"))
        )
    except TimeoutException:
        return 0
    tables = driver.find_elements(By.CSS_SELECTOR, "table[ng-repeat='cann in CorpannData.Table']")
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
                    try:
                        for sp in table.find_elements(By.TAG_NAME, "span"):
                            t = sp.text.strip()
                            if "Announcement under Regulation 30" in t or "Order" in t or "Contract" in t:
                                title = t
                                break
                    except Exception:
                        pass
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
            order_values: List[Dict] = []
            pdf_extract = "PDF not available"
            total_crores = 0.0
            if pdf_link and _is_allowed_pdf_url(pdf_link):
                order_values, pdf_extract = fetch_pdf_and_extract_values(pdf_link)
                total_crores = round(sum(v.get("value_in_crores", 0) for v in order_values), 4)
            sink.append(
                {
                    "page": page_num,
                    "announcement_num": idx,
                    "company": clean_company_name(company, title),
                    "raw_company": company,
                    "title": title,
                    "summary": summary or "No summary available",
                    "pdf_link": pdf_link or "No PDF available",
                    "order_values": order_values,
                    "total_value_crores": round(total_crores, 2),
                    "pdf_extract": (pdf_extract or "")[:500],
                }
            )
            count += 1
        except Exception as e:
            logger.debug(f"Error processing announcement {idx}: {e}")
            continue
    return count

def click_next_if_available(driver: webdriver.Chrome) -> bool:
    try:
        next_btn = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "idnext")))
    except TimeoutException:
        return False
    try:
        if not next_btn.is_displayed():
            return False
        cls = (next_btn.get_attribute("class") or "").lower()
        if "disabled" in cls or "ng-hide" in cls:
            return False
        driver.execute_script("arguments[0].click();", next_btn)
        time.sleep(1.5)
        return True
    except Exception:
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
        try:
            WebDriverWait(driver, SELENIUM_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table[ng-repeat='cann in CorpannData.Table']"))
            )
        except TimeoutException:
            break
        page_num += 1
        time.sleep(1)
    return orders

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "message": "BSE Scraper API is running", "timestamp": datetime.now(timezone.utc).isoformat()}), 200

_visits_lock = threading.Lock()
VISITS_FILE = Path(os.getenv("VISITS_FILE", "data/visits.count"))

def _ensure_visits_file():
    try:
        VISITS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not VISITS_FILE.exists():
            VISITS_FILE.write_text("0")
    except Exception as e:
        logger.warning(f"Could not prepare visits file: {e}")

def _read_visits():
    try:
        return int(VISITS_FILE.read_text().strip())
    except Exception:
        return 0

def _write_visits(v: int):
    try:
        VISITS_FILE.parent.mkdir(parents=True, exist_ok=True)
        VISITS_FILE.write_text(str(v))
    except Exception as e:
        logger.warning(f"Could not write visits file: {e}")

_ensure_visits_file()

@app.route("/api/visit", methods=["POST"])
def visit_hit():
    with _visits_lock:
        v = _read_visits() + 1
        _write_visits(v)
        return jsonify({"visits": v}), 200

@app.route("/api/visit", methods=["GET"])
def visit_get():
    return jsonify({"visits": _read_visits()}), 200

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
    try:
        scrape_manager.start(formatted_date)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    except Exception:
        logger.exception("Failed to start scraper")
        return jsonify({"error": "Failed to start scraping"}), 500
    return jsonify({"message": "Scraping started", "date": formatted_date, "readable_date": date_obj.strftime("%A, %B %d, %Y")}), 202

@app.route("/api/status", methods=["GET"])
def get_status():
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(scrape_manager.get_status()), 200

@app.route("/api/results", methods=["GET"])
def get_results():
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    res = scrape_manager.get_results()
    st = scrape_manager.get_status()
    if res:
        return jsonify(res), 200
    if st.get("error"):
        return jsonify({"error": st["error"]}), 500
    if st.get("is_running"):
        return jsonify({"message": "Scraping is in progress"}), 202
    return jsonify({"message": "No results available"}), 404

@app.route("/api/stop", methods=["POST"])
def stop_scraping():
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    st = scrape_manager.get_status()
    if not st.get("is_running"):
        return jsonify({"message": "No scraping job is currently running"}), 200
    scrape_manager.stop()
    return jsonify({"message": "Stop requested"}), 202

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.exception("Unhandled server error")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")), debug=False)
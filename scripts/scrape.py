"""
SJSU CampusConcourse CMPE Syllabus Scraper
------------------------------------------
Pagination uses form submit with offset, not href links.
We click the Next button directly via Selenium.

Setup:
    sudo apt install -y chromium-browser chromium-driver
    pip install selenium pandas openpyxl

Run:
    python3 scrape.py
"""

import re
import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL  = "https://sjsu.campusconcourse.com"
START_URL = (f"{BASE_URL}/search?search_performed=1"
             f"&sort_by=year&descend=true&prefix=CMPE&template=non")

COLUMNS = [
    "course_title", "subject", "catalog_number", "course_code",
    "session", "year", "section", "instructor", "syllabus_url"
]

# ── driver ────────────────────────────────────────────────────────────────────

def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")

    for path in [
        "/usr/bin/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
        "/usr/lib/chromium/chromedriver",
        "/snap/bin/chromium.chromedriver",
        "chromedriver",
    ]:
        try:
            driver = webdriver.Chrome(service=Service(path), options=opts)
            print(f"  chromedriver: {path}")
            return driver
        except Exception:
            continue

    raise RuntimeError("chromedriver not found. Run: sudo apt install -y chromium-driver")

# ── parse rows on current page ────────────────────────────────────────────────

def parse_page(driver):
    rows = []

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr"))
        )
    except Exception:
        print("  Timed out waiting for results.")
        return rows

    trs = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

    for tr in trs:
        # ── course_title + syllabus_url ──
        try:
            a_tag        = tr.find_element(By.CSS_SELECTOR, "h3 a, h4 a, h5 a, .h5 a")
            course_title = a_tag.text.strip()
            href         = a_tag.get_attribute("href") or ""
            syllabus_url = href if href.startswith("http") else BASE_URL + "/" + href.lstrip("/")
        except Exception:
            continue

        # skip template courses
        if re.search(r"template", course_title, re.I):
            continue

        # ── four col-sm-3 divs: course_code | session+year | section | instructor ──
        cols = tr.find_elements(By.CSS_SELECTOR, "div.col-sm-3")
        c = [col.text.strip() for col in cols]
        while len(c) < 4:
            c.append("")

        # course_code
        course_code    = c[0]
        catalog_number = ""
        m = re.match(r"CMPE-?(\w+)", course_code, re.I)
        if m:
            catalog_number = m.group(1)
            course_code    = f"CMPE-{catalog_number}"

        # session + year
        session = ""
        year    = ""
        for s in ["Spring", "Fall", "Summer", "Winter"]:
            if s in c[1]:
                session = s
                break
        m2 = re.search(r"\b(20\d{2})\b", c[1])
        if m2:
            year = int(m2.group(1))

        # section
        section = ""
        m3 = re.search(r"\d+", c[2])
        if m3:
            section = int(m3.group())

        # instructor
        instructor = c[3]

        rows.append({
            "course_title":   course_title,
            "subject":        "CMPE",
            "catalog_number": catalog_number,
            "course_code":    course_code,
            "session":        session,
            "year":           year,
            "section":        section,
            "instructor":     instructor,
            "syllabus_url":   syllabus_url,
        })

    return rows

# ── click Next button using JS (form submit with offset) ─────────────────────

def click_next(driver):
    """
    The Next button does: $('#offset').val(N); $('#search_form').submit()
    We extract N from the onclick and trigger it directly via JS.
    """
    try:
        next_btn = driver.find_element(
            By.XPATH,
            "//button[contains(text(),'Next') or contains(text(),'next')]"
        )
        onclick = next_btn.get_attribute("onclick") or ""

        # extract the offset value from onclick e.g. "$('#offset').val(1)"
        m = re.search(r"#offset.*?val\((\d+)\)", onclick)
        if not m:
            return False

        offset = m.group(1)
        # set the offset and submit the form via JS
        driver.execute_script(
            f"$('#offset').val({offset}); $('#search_form').trigger('submit');"
        )
        time.sleep(2)  # wait for page to reload
        return True

    except Exception:
        return False

# ── scrape all pages ──────────────────────────────────────────────────────────

def scrape_all():
    driver   = make_driver()
    all_rows = []
    page_num = 1

    try:
        print(f"Opening: {START_URL}\n")
        driver.get(START_URL)
        time.sleep(2)

        while True:
            print(f"  Page {page_num} ...", end=" ", flush=True)
            rows = parse_page(driver)

            if not rows:
                print("no rows — stopping.")
                break

            all_rows.extend(rows)
            print(f"got {len(rows)} (total: {len(all_rows)})")

            # try to go to next page
            if not click_next(driver):
                print("  No next button — done.")
                break

            page_num += 1

    finally:
        driver.quit()

    return all_rows

# ── save CSV + Excel ──────────────────────────────────────────────────────────

def save(rows):
    if not rows:
        print("\nNo data scraped.")
        return

    df = pd.DataFrame(rows, columns=COLUMNS)

    s_ord = {"Spring": 1, "Fall": 2, "Summer": 3, "Winter": 4}
    df["_s"] = df["session"].map(s_ord).fillna(5)
    df = (df.sort_values(["year", "_s", "course_code"],
                         ascending=[False, True, True])
            .drop(columns=["_s"])
            .reset_index(drop=True))

    df.to_csv("cmpe_syllabi.csv", index=False)
    print(f"CSV  -> cmpe_syllabi.csv")

    from openpyxl.styles import Font, PatternFill, Alignment
    with pd.ExcelWriter("cmpe_syllabi.xlsx", engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="CMPE Syllabi")
        ws = writer.sheets["CMPE Syllabi"]

        for col, w in zip("ABCDEFGHI", [45, 8, 15, 15, 8, 6, 8, 28, 60]):
            ws.column_dimensions[col].width = w
        for cell in ws[1]:
            cell.font      = Font(bold=True, name="Arial", size=10)
            cell.fill      = PatternFill("solid", start_color="DDEEFF")
            cell.alignment = Alignment(horizontal="center")
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name="Arial", size=10)

    print(f"XLSX -> cmpe_syllabi.xlsx")
    years = df["year"].dropna().astype(int)
    print(f"\nTotal rows : {len(df)}")
    print(f"Year range : {years.max()} -> {years.min()}")

# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    rows = scrape_all()
    save(rows)

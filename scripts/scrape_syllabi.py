"""
Setup:
    pip install playwright pandas
    playwright install chromium
 
Run:
    python3 scrape_syllabi.py
"""

import re
import time
import random
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

YEARS = [2025, 2026]
BASE_URL = "https://sjsu.campusconcourse.com"
START_URLS = [
    f"{BASE_URL}/search?search_performed=1&sort_by=credits&year={year}&template=non"
    for year in YEARS
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

CSV_COLUMNS = [
    "department",
    "catalog_number",
    "course_title",
    "units",
    "instructor_name",
    "year",
    "session",
    "section",
    "syllabus_url",
]


# ── context factory ────────────────────────────────────────────────────────────

def new_context(browser, ua_index: int = 0):
    return browser.new_context(
        user_agent=USER_AGENTS[ua_index % len(USER_AGENTS)]
    )


# ── pass 1: collect rows from search-result pages ─────────────────────────────

def collect_search_rows(page) -> list[dict]:
    """Parse the current search-results page; return one dict per row."""
    rows = []
    try:
        page.wait_for_selector("tbody tr", timeout=20_000)
    except PWTimeout:
        print("  [timeout waiting for results]")
        return rows

    for tr in page.query_selector_all("tbody tr"):
        # 1. Capture and Clean Course Title
        a = tr.query_selector("h3 a, h4 a, h5 a, .h5 a")
        if not a:
            continue

        raw_title = (a.inner_text() or "").strip()

        # Check for section in title and clean it regardless of priority
        section_in_title = None
        match_section = re.search(r"\s+Section\s+(\d+)", raw_title, re.I)
        if match_section:
            section_in_title = [int(match_section.group(1))]
            course_title = re.sub(r"\s+Section\s+\d+", "", raw_title, flags=re.I).strip()
        else:
            course_title = raw_title

        href = a.get_attribute("href") or ""
        syllabus_url = href if href.startswith("http") else BASE_URL + "/" + href.lstrip("/")

        if re.search(r"template", course_title, re.I):
            continue

        # 2. Parse Columns
        cols = [c.inner_text().strip() for c in tr.query_selector_all("div.col-sm-3")]
        while len(cols) < 4:
            cols.append("")

        # 3. Handle Section Priority
        section_from_col = [int(m.group()) for m in re.finditer(r"\d+", cols[2])]
        section = section_from_col if section_from_col else section_in_title

        credits = None
        credit_td = tr.query_selector("td.align-bottom")
        if credit_td:
            m_credits = re.search(r"([\d.]+)", credit_td.inner_text())
            if m_credits:
                credits = float(m_credits.group(1))

        department = ""
        catalog_number = ""
        m = re.match(r"([A-Z0-9]+)-(\w+)", cols[0], re.I)
        if m:
            department = m.group(1).upper()
            catalog_number = m.group(2).upper()

        session = next((s for s in ("Spring", "Fall", "Summer", "Winter") if s in cols[1]), "")
        m2 = re.search(r"\b(20\d{2})\b", cols[1])
        year = int(m2.group(1)) if m2 else ""
        instructor_name = cols[3]
        if instructor_name == ',':
            continue

        if not all([department, catalog_number, course_title, instructor_name, year, session, section, credits, syllabus_url]):
            continue

        rows.append({
            "department":      department,
            "catalog_number":  catalog_number,
            "course_title":    course_title,
            "instructor_name": instructor_name,
            "year":            year,
            "session":         session,
            "section":         section,
            "units":           credits,
            "syllabus_url":    syllabus_url,
        })
    return rows


def click_next(page) -> bool:
    """Advance to the next search-results page via JS form submit."""
    try:
        btn = page.query_selector("button:has-text('Next'), button:has-text('next')")
        if not btn:
            print("  [click_next] No Next button found in DOM")
            return False
        onclick = btn.get_attribute("onclick") or ""
        # handle both val(227) and val('227')
        m = re.search(r"#offset.*?val\(['\"]?(\d+)['\"]?\)", onclick)
        if not m:
            print(f"  [click_next] Regex didn't match onclick: {repr(onclick)}")
            return False
        offset = m.group(1)
        page.evaluate(
            f"() => {{ $('#offset').val({offset}); $('#search_form').trigger('submit'); }}"
        )
        page.wait_for_selector("tbody tr", timeout=15_000)
        time.sleep(random.uniform(2, 5))  # randomised delay instead of fixed 1s
        return True
    except PWTimeout:
        print("  [click_next] Timeout waiting for next page to load")
        return False
    except Exception as e:
        print(f"  [click_next] Unexpected error: {e}")
        return False


# ── save to CSV ────────────────────────────────────────────────────────────────

def save_csv(rows: list[dict], path: str = "cmpe_syllabi_db.csv"):
    if not rows:
        print("\nNo data scraped — nothing saved.")
        return

    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    df = df.explode("section").reset_index(drop=True)
    df.to_csv(path, index=False)

    print(f"\n{'─'*50}")
    print(f"  Saved : {path}")
    print(f"  Rows  : {len(df)}")
    if not df['year'].empty:
        print(f"  Years : {df['year'].max()} → {df['year'].min()}")
    print(f"{'─'*50}\n")
    print(df.head(10).to_string())


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    all_rows: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ua_index = 0
        context = new_context(browser, ua_index)
        page = context.new_page()

        print(f"\nPass 1 — collecting search results …\n")
        pg = 1

        for current_year, url in zip(YEARS, START_URLS):
            m_offset = re.search(r"offset=(\d+)", url)
            current_offset = int(m_offset.group(1)) if m_offset else 0

            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
            print(f"Year: {current_year} (starting offset: {current_offset})")

            while True:
                print(f"  Page {pg} (offset {current_offset}) … ", end="", flush=True)
                rows = collect_search_rows(page)
                all_rows.extend(rows)
                print(f"{len(rows)} rows  (total: {len(all_rows)})")

                # ── capture next offset BEFORE anything else ──────────────────
                btn = page.query_selector("button:has-text('Next')")
                if btn:
                    onclick = btn.get_attribute("onclick") or ""
                    m = re.search(r"val\(['\"]?(\d+)['\"]?\)", onclick)
                    if m:
                        current_offset = int(m.group(1))

                # ── small cooldown every 50 pages (skip on hard reset pages) ──
                if pg % 50 == 0 and pg % 200 != 0:
                    cooldown = random.uniform(120, 180)
                    print(f"  Cooldown at page {pg} — sleeping {cooldown:.0f}s")
                    time.sleep(cooldown)

                # ── hard reset every 200 pages ────────────────────────────────
                if pg % 200 == 0:
                    print(f"  Hard reset at page {pg} — sleeping 120s + restarting context")
                    time.sleep(120)
                    context.close()
                    ua_index += 1
                    context = new_context(browser, ua_index)
                    page = context.new_page()
                    resume_url = (
                        f"{BASE_URL}/search?search_performed=1"
                        f"&offset={current_offset}"
                        f"&sort_by=credits"
                        f"&year={current_year}"
                        f"&template=non"
                    )
                    print(f"  Resuming at: {resume_url}")
                    page.goto(resume_url, wait_until="domcontentloaded", timeout=30_000)
                    time.sleep(2)
                    pg += 1
                    continue  # skip click_next — already on the right page

                if not click_next(page):
                    print("  No Next button — search complete for this year.")
                    break

                pg += 1

        browser.close()

    save_csv(all_rows)


if __name__ == "__main__":
    main()
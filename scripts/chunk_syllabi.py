import re
import time
import threading
import requests
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV     = os.path.join(BASE_DIR, "cmpe_syllabi_db.csv")
OUTPUT_CSV    = os.path.join(BASE_DIR, "chunks.csv")

MAX_WORKERS   = 25
REQUEST_DELAY = 0.1

# ── Session with realistic browser headers ────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

# ── 1. Load sections from CSV ─────────────────────────────────────────────────

def fetch_sections(input_csv: str) -> list[dict]:
    df = pd.read_csv(input_csv, dtype=str).fillna("")
    sections = []
    for _, row in df.iterrows():
        url = row["syllabus_url"].strip()
        if not url:
            continue
        sections.append({
            "subject":        row["subject"],
            "catalog_number": row["catalog_number"],
            "session":        row["session"],
            "year":           row["year"],
            "section":        row["section"],
            "course_title":   row["course_title"],
            "url":            url,
        })
    return sections

# ── 2. Scrape & chunk syllabus by section headings ────────────────────────────

_throttle = threading.Semaphore(MAX_WORKERS)

def fetch_syllabus_text(url: str) -> BeautifulSoup | None:
    with _throttle:
        time.sleep(REQUEST_DELAY)
        try:
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            print(f"  [ERROR] Could not fetch {url}: {e}")
            return None

def chunk_by_headings(soup: BeautifulSoup) -> list[dict]:
    chunks = []

    # ── Header chunk: Section Information ────────────────────────────────────
    header = soup.find(class_="syl-header")
    if header:
        h1 = header.find("h1")
        if h1:
            course_name = h1.get_text(separator=" ", strip=True)
            meta_items  = [li.get_text(strip=True) for li in header.find_all("li", class_="list-inline-item")]
            content     = " ".join([course_name] + meta_items)
            chunks.append({"title": "Section Information", "content": content})

    # ── l1 section chunks ─────────────────────────────────────────────────────
    sections = soup.find_all("div", class_="syl-item-l1")

    if sections:
        for section in sections:
            title_tag = section.find(class_="category-label")
            title = title_tag.get_text(separator=" ", strip=True) if title_tag else "Untitled"

            content_parts = []

            content_div = section.find(class_="indent-one")
            if content_div:
                text = " ".join(content_div.get_text(separator=" ", strip=True).split())
                if text:
                    content_parts.append(text)

            for sibling in section.find_next_siblings("div"):
                classes = sibling.get("class", [])
                if "syl-item-l1" in classes:
                    break
                if "syl-item-l2" in classes:
                    label_tag = sibling.find(class_="item-label")
                    l2_title  = label_tag.get_text(strip=True) if label_tag else ""
                    l2_div    = sibling.find(class_="indent-one")
                    l2_text   = " ".join(l2_div.get_text(separator=" ", strip=True).split()) if l2_div else ""
                    if l2_text:
                        content_parts.append(f"{l2_title}: {l2_text}" if l2_title else l2_text)

            content = " ".join(content_parts)
            if content:
                chunks.append({"title": title, "content": content})
    else:
        # Fallback: split on blank lines
        body_text  = soup.get_text(separator="\n")
        paragraphs = re.split(r"\n{2,}", body_text)
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if len(para) > 80:
                chunks.append({"title": f"Paragraph {i+1}", "content": para})

    return chunks

def process_section(sec: dict) -> list[dict]:
    """Fetch + chunk one section. Returns a list of row dicts (empty if skipped)."""
    soup = fetch_syllabus_text(sec["url"])
    if soup is None:
        return []

    chunks = chunk_by_headings(soup)

    if len(chunks) <= 1:
        return []

    return [
        {
            "subject":        sec["subject"],
            "catalog_number": sec["catalog_number"],
            "session":        sec["session"],
            "year":           sec["year"],
            "section":        sec["section"],
            "chunk_title":    chunk["title"],
            "chunk_text":     chunk["content"],
        }
        for chunk in chunks
    ]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    sections = fetch_sections(INPUT_CSV)
    total    = len(sections)
    print(f"Found {total} section(s) to process. Running with {MAX_WORKERS} workers.\n")

    rows      = []
    completed = 0
    lock      = threading.Lock()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_section, sec): sec for sec in sections}

        for future in as_completed(futures):
            sec = futures[future]
            label = f"{sec['subject']} {sec['catalog_number']} {sec['section']} {sec['year']} {sec['session']} {sec['url']}"

            with lock:
                completed += 1
                progress = f"[{completed}/{total}]"

            try:
                result = future.result()
            except Exception as e:
                print(f"{progress} [ERROR] {label}: {e}")
                continue

            if not result:
                print(f"{progress} [SKIPPED] {label} (private or no content)")
            else:
                print(f"{progress} [OK] {label} — {len(result)} chunk(s)")
                with lock:
                    rows.extend(result)

    df_out = pd.DataFrame(rows, columns=["subject", "catalog_number", "session", "year", "section", "chunk_title", "chunk_text"])
    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"\nDone. Wrote {len(df_out)} chunk(s) to '{OUTPUT_CSV}'.")

if __name__ == "__main__":
    main()

import os
import re
import time
import psycopg2
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from dotenv import load_dotenv
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     os.getenv("DB_PORT", 5432),
    "dbname":   os.getenv("DB_NAME", "your_db"),
    "user":     os.getenv("DB_USER", "your_user"),
    "password": os.getenv("DB_PASSWORD", "your_password"),
}

GEMINI_API_KEY   = os.getenv("GOOGLE_API_KEY")
EMBEDDING_MODEL  = "gemini-embedding-001"   # 768-dim output
EMBED_TASK_TYPE  = "RETRIEVAL_DOCUMENT"
RATE_LIMIT_DELAY = 0.5                      # seconds between embedding calls

client = genai.Client(api_key=GEMINI_API_KEY)

# ── 1. Fetch all syllabus URLs from DB ────────────────────────────────────────

def fetch_sections(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT section_id, course, syllabus_url FROM section;")
        rows = cur.fetchall()
    return [{"section_id": r[0], "course": r[1], "url": r[2]} for r in rows]

# ── 2. Scrape & chunk syllabus by section headings ────────────────────────────

def fetch_syllabus_text(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [ERROR] Could not fetch {url}: {e}")
        return None

def chunk_by_headings(soup: BeautifulSoup) -> list[dict]:
    chunks = []

    # Each top-level syllabus section is a div with class 'syl-item-l1'
    sections = soup.find_all("div", class_="syl-item-l1")

    if sections:
        for section in sections:
            title_tag = section.find(class_="category-label")
            title = title_tag.get_text(separator=" ", strip=True) if title_tag else "Untitled"

            content_div = section.find(class_="indent-one")
            content = content_div.get_text(separator=" ", strip=True) if content_div else ""

            if content:
                chunks.append({"title": title, "content": f"{title}\n{content}"})

    else:
        # Fallback: split on blank lines
        body_text = soup.get_text(separator="\n")
        paragraphs = re.split(r"\n{2,}", body_text)
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if len(para) > 80:
                chunks.append({"title": f"Paragraph {i+1}", "content": para})

    return chunks

# ── 3. Generate embedding via Gemini embedding-001 ────────────────────────────

def embed_text(text: str) -> list[float]:
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type=EMBED_TASK_TYPE)
    )
    return result.embeddings[0].values

# ── 4. Insert chunks + embeddings into DB ─────────────────────────────────────

def insert_chunks(conn, section_id: int, chunks: list[dict]):
    with conn.cursor() as cur:
        for chunk in chunks:
            cur.execute(
                """
                INSERT INTO syllabus_chunks (section_id, chunk_text, embedding)
                VALUES (%s, %s, %s::vector);
                """,
                (section_id, chunk["content"], str(chunk["embedding"])),
            )
    conn.commit()

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    print("Connected to database.\n")

    sections = fetch_sections(conn)
    print(f"Found {len(sections)} section(s) to process.\n")

    for section in sections:
        sid  = section["section_id"]
        url  = section["url"]
        name = section["course"]
        print(f"[{name}] section_id={sid}")
        print(f"  Fetching: {url}")

        soup = fetch_syllabus_text(url)
        if soup is None:
            continue

        raw_chunks = chunk_by_headings(soup)
        print(f"  Found {len(raw_chunks)} chunk(s). Embedding...")

        embedded_chunks = []
        for i, chunk in enumerate(raw_chunks):
            try:
                vector = embed_text(chunk["content"])
                embedded_chunks.append({**chunk, "embedding": vector})
                print(f"    [{i+1}/{len(raw_chunks)}] '{chunk['title'][:50]}' ✓")
                time.sleep(RATE_LIMIT_DELAY)   # respect API rate limits
            except Exception as e:
                print(f"    [{i+1}/{len(raw_chunks)}] FAILED to embed '{chunk['title']}': {e}")

        if embedded_chunks:
            insert_chunks(conn, sid, embedded_chunks)
            print(f"  Inserted {len(embedded_chunks)} chunk(s) into syllabus_chunks.\n")

    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()

-- CTE pre-filters to chunk_id integers only — the outer query joins back to the
-- physical syllabus_chunk table so pgvector can engage the HNSW index for ORDER BY.
-- Pulling embedding into the CTE (previous approach) materialised a derived relation
-- that blocked HNSW and forced a brute-force distance scan on all matching rows.
--
-- %s appears twice per query (similarity + ORDER BY); the benchmark runner
-- binds the same vector to $1 and $2.

-- ─────────────────────────────────────────────────────────────────
-- TEST 1: No filters — pure vector search
-- Targets: idx_syllabus_embedding_hnsw
-- Baseline: no WHERE clause, HNSW should drive the ORDER BY directly.
-- ─────────────────────────────────────────────────────────────────
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
WITH filtered_ids AS (
    SELECT sc.chunk_id
    FROM syllabus_chunk sc
    JOIN section    s ON s.section_id    = sc.section_id
    JOIN course     c ON c.course_id     = s.course_id
    JOIN instructor i ON i.instructor_id = s.instructor_id
)
SELECT
    sc.chunk_id, sc.chunk_title, sc.chunk_text,
    c.subject, c.catalog_number,
    s.course_title, s.units, s.session, s.year, s.section, s.delivery, s.syllabus_url,
    i.instructor_name,
    1 - (sc.embedding <=> %s) AS similarity
FROM syllabus_chunk sc
JOIN filtered_ids fi ON fi.chunk_id    = sc.chunk_id
JOIN section      s  ON s.section_id   = sc.section_id
JOIN course       c  ON c.course_id    = s.course_id
JOIN instructor   i  ON i.instructor_id = s.instructor_id
ORDER BY sc.embedding <=> %s
LIMIT 10;

-- ─────────────────────────────────────────────────────────────────
-- TEST 2: Filter by catalog_number
-- Targets: idx_course_catalog_number
-- NOTE: idx_course_subject is redundant — the existing unique constraint on
-- (subject, catalog_number) already covers subject-only lookups, so that
-- index was dropped. catalog_number alone is not covered by the constraint.
-- ─────────────────────────────────────────────────────────────────
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
WITH filtered_ids AS (
    SELECT sc.chunk_id
    FROM syllabus_chunk sc
    JOIN section    s ON s.section_id    = sc.section_id
    JOIN course     c ON c.course_id     = s.course_id
    JOIN instructor i ON i.instructor_id = s.instructor_id
    WHERE c.catalog_number = '180B'
)
SELECT
    sc.chunk_id, sc.chunk_title, sc.chunk_text,
    c.subject, c.catalog_number,
    s.course_title, s.units, s.session, s.year, s.section, s.delivery, s.syllabus_url,
    i.instructor_name,
    1 - (sc.embedding <=> %s) AS similarity
FROM syllabus_chunk sc
JOIN filtered_ids fi ON fi.chunk_id     = sc.chunk_id
JOIN section      s  ON s.section_id   = sc.section_id
JOIN course       c  ON c.course_id    = s.course_id
JOIN instructor   i  ON i.instructor_id = s.instructor_id
ORDER BY sc.embedding <=> %s
LIMIT 10;

-- ─────────────────────────────────────────────────────────────────
-- TEST 3: Filter by instructor name (ILIKE with leading wildcard)
-- Targets: idx_instructor_name_trgm
-- GIN trigram resolves the ILIKE in the CTE; HNSW ranks survivors.
-- ─────────────────────────────────────────────────────────────────
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
WITH filtered_ids AS (
    SELECT sc.chunk_id
    FROM syllabus_chunk sc
    JOIN section    s ON s.section_id    = sc.section_id
    JOIN course     c ON c.course_id     = s.course_id
    JOIN instructor i ON i.instructor_id = s.instructor_id
    WHERE i.instructor_name ILIKE '%Bond%'
)
SELECT
    sc.chunk_id, sc.chunk_title, sc.chunk_text,
    c.subject, c.catalog_number,
    s.course_title, s.units, s.session, s.year, s.section, s.delivery, s.syllabus_url,
    i.instructor_name,
    1 - (sc.embedding <=> %s) AS similarity
FROM syllabus_chunk sc
JOIN filtered_ids fi ON fi.chunk_id     = sc.chunk_id
JOIN section      s  ON s.section_id   = sc.section_id
JOIN course       c  ON c.course_id    = s.course_id
JOIN instructor   i  ON i.instructor_id = s.instructor_id
ORDER BY sc.embedding <=> %s
LIMIT 10;

-- ─────────────────────────────────────────────────────────────────
-- TEST 4: Filter by section
-- Targets: idx_section_section
-- ─────────────────────────────────────────────────────────────────
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
WITH filtered_ids AS (
    SELECT sc.chunk_id
    FROM syllabus_chunk sc
    JOIN section    s ON s.section_id    = sc.section_id
    JOIN course     c ON c.course_id     = s.course_id
    JOIN instructor i ON i.instructor_id = s.instructor_id
    WHERE s.section = '1'
)
SELECT
    sc.chunk_id, sc.chunk_title, sc.chunk_text,
    c.subject, c.catalog_number,
    s.course_title, s.units, s.session, s.year, s.section, s.delivery, s.syllabus_url,
    i.instructor_name,
    1 - (sc.embedding <=> %s) AS similarity
FROM syllabus_chunk sc
JOIN filtered_ids fi ON fi.chunk_id     = sc.chunk_id
JOIN section      s  ON s.section_id   = sc.section_id
JOIN course       c  ON c.course_id    = s.course_id
JOIN instructor   i  ON i.instructor_id = s.instructor_id
ORDER BY sc.embedding <=> %s
LIMIT 10;

-- ─────────────────────────────────────────────────────────────────
-- TEST 5: Filter by delivery mode
-- Targets: idx_section_delivery
-- NOTE: 'In Person' covers ~63% of sections — low selectivity by design.
-- Expect modest gains here regardless of indexing; included to confirm
-- the planner skips the index correctly on non-selective filters.
-- ─────────────────────────────────────────────────────────────────
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
WITH filtered_ids AS (
    SELECT sc.chunk_id
    FROM syllabus_chunk sc
    JOIN section    s ON s.section_id    = sc.section_id
    JOIN course     c ON c.course_id     = s.course_id
    JOIN instructor i ON i.instructor_id = s.instructor_id
    WHERE s.delivery = 'In Person'
)
SELECT
    sc.chunk_id, sc.chunk_title, sc.chunk_text,
    c.subject, c.catalog_number,
    s.course_title, s.units, s.session, s.year, s.section, s.delivery, s.syllabus_url,
    i.instructor_name,
    1 - (sc.embedding <=> %s) AS similarity
FROM syllabus_chunk sc
JOIN filtered_ids fi ON fi.chunk_id     = sc.chunk_id
JOIN section      s  ON s.section_id   = sc.section_id
JOIN course       c  ON c.course_id    = s.course_id
JOIN instructor   i  ON i.instructor_id = s.instructor_id
ORDER BY sc.embedding <=> %s
LIMIT 10;

-- ─────────────────────────────────────────────────────────────────
-- TEST 6: Filter by year + session (composite index)
-- Targets: idx_section_lookup
-- Fixed: year=2024 doesn't exist in the dataset (data runs 2025–2026).
-- Fall 2025 covers ~6,028 of 20,437 sections (~29%) — real selectivity.
-- ─────────────────────────────────────────────────────────────────
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
WITH filtered_ids AS (
    SELECT sc.chunk_id
    FROM syllabus_chunk sc
    JOIN section    s ON s.section_id    = sc.section_id
    JOIN course     c ON c.course_id     = s.course_id
    JOIN instructor i ON i.instructor_id = s.instructor_id
    WHERE s.year = 2026 AND s.session = 'Spring'
)
SELECT
    sc.chunk_id, sc.chunk_title, sc.chunk_text,
    c.subject, c.catalog_number,
    s.course_title, s.units, s.session, s.year, s.section, s.delivery, s.syllabus_url,
    i.instructor_name,
    1 - (sc.embedding <=> %s) AS similarity
FROM syllabus_chunk sc
JOIN filtered_ids fi ON fi.chunk_id     = sc.chunk_id
JOIN section      s  ON s.section_id   = sc.section_id
JOIN course       c  ON c.course_id    = s.course_id
JOIN instructor   i  ON i.instructor_id = s.instructor_id
ORDER BY sc.embedding <=> %s
LIMIT 10;

-- ─────────────────────────────────────────────────────────────────
-- TEST 7: Heavy filter — subject + catalog_number + year + session + instructor ILIKE
-- Targets: idx_course_catalog_number (via unique constraint), idx_section_lookup,
--          idx_instructor_name_trgm
-- Fixed: year=2024 → year=2025. This is the most realistic fully-specified
-- user query; the CTE should shrink the candidate set substantially before
-- HNSW ranks the survivors.
-- ─────────────────────────────────────────────────────────────────
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
WITH filtered_ids AS (
    SELECT sc.chunk_id
    FROM syllabus_chunk sc
    JOIN section    s ON s.section_id    = sc.section_id
    JOIN course     c ON c.course_id     = s.course_id
    JOIN instructor i ON i.instructor_id = s.instructor_id
    WHERE c.subject = 'CMPE'
      AND c.catalog_number = '180B'
      AND s.year = 2026
      AND s.session = 'Spring'
      AND i.instructor_name ILIKE '%Bond%'
)
SELECT
    sc.chunk_id, sc.chunk_title, sc.chunk_text,
    c.subject, c.catalog_number,
    s.course_title, s.units, s.session, s.year, s.section, s.delivery, s.syllabus_url,
    i.instructor_name,
    1 - (sc.embedding <=> %s) AS similarity
FROM syllabus_chunk sc
JOIN filtered_ids fi ON fi.chunk_id     = sc.chunk_id
JOIN section      s  ON s.section_id   = sc.section_id
JOIN course       c  ON c.course_id    = s.course_id
JOIN instructor   i  ON i.instructor_id = s.instructor_id
ORDER BY sc.embedding <=> %s
LIMIT 10;

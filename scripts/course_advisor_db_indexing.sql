-- ─────────────────────────────────────────────
--  PERFORMANCE INDEXES
-- ─────────────────────────────────────────────

-- 1. HNSW for Vector Similarity (Critical for RAG performance)
--    m = 16 controls graph connectivity (higher = better recall, more memory)
--    ef_construction = 64 controls build-time quality (higher = slower build, better index)
--    Tip: SET hnsw.ef_search = 100 at query time to trade speed for recall.
CREATE INDEX IF NOT EXISTS idx_syllabus_embedding_hnsw
ON syllabus_chunk USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 2. Foreign Keys (Speeds up multi-table JOINs)
CREATE INDEX IF NOT EXISTS idx_chunk_section_id      ON syllabus_chunk(section_id);
CREATE INDEX IF NOT EXISTS idx_section_course_id     ON section(course_id);
CREATE INDEX IF NOT EXISTS idx_section_instructor_id ON section(instructor_id);

-- 3. Composite Index for common section lookups
CREATE INDEX IF NOT EXISTS idx_section_lookup ON section(year, session);

-- 4. Filter columns on `course` table (WHERE c.subject / c.catalog_number)
CREATE INDEX IF NOT EXISTS idx_course_subject        ON course(subject);
CREATE INDEX IF NOT EXISTS idx_course_catalog_number ON course(catalog_number);

-- 5. Filter columns on `section` table (WHERE s.section / s.delivery)
CREATE INDEX IF NOT EXISTS idx_section_section  ON section(section);
CREATE INDEX IF NOT EXISTS idx_section_delivery ON section(delivery);

-- 6. Trigram index for instructor name ILIKE search
--    A standard btree index is useless for ILIKE '%name%' (leading wildcard).
--    pg_trgm breaks the string into trigrams so the GIN index can still be used.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_instructor_name_trgm
ON instructor USING gin (instructor_name gin_trgm_ops);

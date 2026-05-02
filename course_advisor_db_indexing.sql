-- ─────────────────────────────────────────────
--  PERFORMANCE INDEXES
-- ─────────────────────────────────────────────

-- 1. HNSW for Vector Similarity (Critical for RAG performance)
CREATE INDEX IF NOT EXISTS idx_syllabus_embedding_hnsw 
ON syllabus_chunk USING hnsw (embedding vector_cosine_ops);

-- 2. Foreign Keys (Speeds up multi-table JOINs)
CREATE INDEX IF NOT EXISTS idx_chunk_section_id ON syllabus_chunk(section_id);
CREATE INDEX IF NOT EXISTS idx_section_course_id ON section(course_id);
CREATE INDEX IF NOT EXISTS idx_section_instructor_id ON section(instructor_id);

-- 3. Composite Index for common lookups
CREATE INDEX IF NOT EXISTS idx_section_lookup ON section(year, session);
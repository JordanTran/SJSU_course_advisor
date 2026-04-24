-- 1. DROP ALL INDEXES (Baseline)
DROP INDEX IF EXISTS idx_hnsw_embedding;
DROP INDEX IF EXISTS idx_sc_section;
DROP INDEX IF EXISTS idx_s_course;
DROP INDEX IF EXISTS idx_s_term;

-- 2. VECTOR TEST (Baseline)
-- @TEST_VECTOR_BEFORE
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT chunk_id FROM syllabus_chunk ORDER BY embedding <=> %s LIMIT 5;

-- 3. APPLY ALL INDEXES
CREATE INDEX idx_hnsw_embedding ON syllabus_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_sc_section ON syllabus_chunk(section_id);
CREATE INDEX idx_s_course ON section(course_id);
CREATE INDEX idx_s_term ON section(year, session);

-- 4. VECTOR TEST (Optimized)
-- @TEST_VECTOR_AFTER
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT chunk_id FROM syllabus_chunk ORDER BY embedding <=> %s LIMIT 5;

-- 5. RELATIONAL JOIN TEST (Optimized)
-- @TEST_JOIN_AFTER
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT sc.chunk_id FROM syllabus_chunk sc
JOIN section s ON sc.section_id = s.section_id
JOIN course c ON s.course_id = c.course_id
WHERE c.subject = 'CS' AND c.catalog_number = '146';
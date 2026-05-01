-- 1. Setup Baseline Environment
-- Create unindexed copy of the heavy vector table
DROP TABLE IF EXISTS syllabus_chunk_baseline;
CREATE TABLE syllabus_chunk_baseline AS SELECT * FROM syllabus_chunk;

-- Temporarily drop the small relational indexes for baseline testing
DROP INDEX IF EXISTS idx_sc_section;
DROP INDEX IF EXISTS idx_s_course;
DROP INDEX IF EXISTS idx_s_term;

-- 2. Vector Search (Baseline)
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT chunk_id FROM syllabus_chunk_baseline ORDER BY embedding <=> %s LIMIT 5;

-- 3. Relational Join (Baseline)
-- This will now run without indexes on section or course
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT sc.chunk_id FROM syllabus_chunk sc
JOIN section s ON sc.section_id = s.section_id
JOIN course c ON s.course_id = c.course_id
WHERE c.subject = 'CS' AND c.catalog_number = '146';

-- 4. Re-apply Relational Indexes for Optimized Tests
CREATE INDEX idx_sc_section ON syllabus_chunk(section_id);
CREATE INDEX idx_s_course ON section(course_id);
CREATE INDEX idx_s_term ON section(year, session);

-- 5. Vector Search (Optimized)
-- Runs against the original table which already has idx_hnsw_embedding
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT chunk_id FROM syllabus_chunk ORDER BY embedding <=> %s LIMIT 5;

-- 6. Relational Join (Optimized)
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT sc.chunk_id FROM syllabus_chunk sc
JOIN section s ON sc.section_id = s.section_id
JOIN course c ON s.course_id = c.course_id
WHERE c.subject = 'CS' AND c.catalog_number = '146';

-- 7. Cleanup
DROP TABLE IF EXISTS syllabus_chunk_baseline;
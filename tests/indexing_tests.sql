-- TEST 1: Targets idx_syllabus_embedding_hnsw
-- Checks vector search performance
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT chunk_id FROM syllabus_chunk 
ORDER BY embedding <=> %s LIMIT 5;

-- TEST 2: Targets idx_chunk_section_id
-- Checks the join between chunks and sections
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT sc.chunk_id FROM syllabus_chunk sc
JOIN section s ON sc.section_id = s.section_id
WHERE s.section = '01';

-- TEST 3: Targets idx_section_course_id
-- Checks the join between sections and courses
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT s.section_id FROM section s
JOIN course c ON s.course_id = c.course_id
WHERE c.catalog_number = '146';

-- TEST 4: Targets idx_section_instructor_id
-- Checks the join between sections and instructors
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT s.section_id FROM section s
JOIN instructor i ON s.instructor_id = i.instructor_id
WHERE i.instructor_name = 'Smith';

-- TEST 5: Targets idx_section_lookup (Composite)
-- Checks filtering by year, session, and section
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT section_id FROM section 
WHERE year = 2024 AND session = 'Fall' AND section = '01';
-- =====================================================
-- TEST SCRIPT: FULL DATABASE TEST (CRUD + QUERIES + RAG)
-- =====================================================

-- =========================
-- 1. INSERT FAKE DATA
-- =========================

-- Department
INSERT INTO department (department, department_name, college)
VALUES ('CSE', 'Computer Science & Engineering', 'Engineering');

-- Course
INSERT INTO course (department, catalog_number, course_title, units)
VALUES ('CSE', '101', 'Intro to Testing Systems', 3);

-- Instructor
INSERT INTO instructor (instructor_name)
VALUES ('Test, Alice'), ('Test, Bob');

-- Sections
INSERT INTO section (course_id, year, session, section, instructor_id, delivery, syllabus_url)
VALUES
    ((SELECT course_id FROM course WHERE department='CSE' AND catalog_number='101'), 2023, 'Fall', '1', 1, 'Online', 'url1'),
    ((SELECT course_id FROM course WHERE department='CSE' AND catalog_number='101'), 2024, 'Spring', '2', 2, 'In-Person', 'url2');

-- Syllabus Chunks (fake embeddings)
INSERT INTO syllabus_chunk (section_id, chunk_text, embedding)
VALUES
    ( (SELECT section_id FROM section WHERE year=2023 LIMIT 1), 'Intro syllabus content', '[0.1,0.2,0.3]' ),
    ( (SELECT section_id FROM section WHERE year=2024 LIMIT 1), 'Advanced syllabus content', '[0.2,0.3,0.4]' );


-- =========================
-- 2. CRUD TESTS
-- =========================

-- CREATE
INSERT INTO section (course_id, year, session, section, instructor_id, delivery)
VALUES ((SELECT course_id FROM course WHERE department='CSE' AND catalog_number='101'),
        2025, 'Fall', '99', 1, 'Hybrid');

SELECT * FROM section WHERE year = 2025;

-- READ
SELECT * FROM section;

-- UPDATE
UPDATE section
SET delivery = 'Online'
WHERE year = 2025;

SELECT * FROM section WHERE year = 2025;

-- DELETE
DELETE FROM section WHERE year = 2025;
SELECT * FROM section WHERE year = 2025;


-- =========================
-- 3. CORE QUERIES
-- =========================

-- Given course code -> get sections
SELECT s.*
FROM section s
JOIN course c ON s.course_id = c.course_id
WHERE c.department = 'CSE'
  AND c.catalog_number = '101';

-- Given section_id -> get everything
SELECT s.section_id, c.course_title, i.instructor_name, s.year, s.session
FROM section s
JOIN course c ON s.course_id = c.course_id
JOIN instructor i ON s.instructor_id = i.instructor_id
WHERE s.section_id = (SELECT MIN(section_id) FROM section);

-- Range query
SELECT s.*
FROM section s
JOIN course c ON s.course_id = c.course_id
WHERE c.department = 'CSE'
  AND c.catalog_number = '101'
  AND s.year BETWEEN 2023 AND 2025;

-- By instructor
SELECT s.*
FROM section s
JOIN instructor i ON s.instructor_id = i.instructor_id
WHERE i.instructor_name = 'Test, Alice';


-- =========================
-- 4. RAG / CHUNK TEST
-- =========================

-- SELECT sc.chunk_id, sc.chunk_text, sc.section_id
-- FROM syllabus_chunk sc
-- JOIN section s ON sc.section_id = s.section_id
-- WHERE s.year = 2023;


-- =========================
-- 5. TRANSACTION TEST "T in acid"
-- =========================

BEGIN;

INSERT INTO instructor (instructor_name)
VALUES ('Temp Instructor');

ROLLBACK;

--Should return nothing
SELECT * FROM instructor WHERE instructor_name = 'Temp Instructor';


-- =========================
-- 6. INDEX + PERFORMANCE
-- =========================

-- Without index
-- EXPLAIN ANALYZE
-- SELECT * FROM section WHERE year = 2024;

-- -- Create index
-- CREATE INDEX idx_section_year ON section(year);

-- -- With index
-- EXPLAIN ANALYZE
-- SELECT * FROM section WHERE year = 2024;


-- =========================
-- 7. DATA INTEGRITY TESTS
-- =========================

-- Should FAIL (duplicate course)
-- INSERT INTO course (department, catalog_number, course_title, units)
-- VALUES ('CSE', '101', 'Duplicate', 3);

-- Should FAIL (invalid foreign key)
-- INSERT INTO section (course_id, year, session, section, instructor_id)
-- VALUES (9999, 2026, 'Fall', '1', 1);


-- =========================
-- 8. CLEANUP (DELETE FAKE DATA)
-- =========================

DELETE FROM syllabus_chunk
WHERE section_id IN (
    SELECT section_id FROM section
    WHERE course_id IN (
        SELECT course_id FROM course WHERE department='CSE'
    )
);

DELETE FROM section
WHERE course_id IN (
    SELECT course_id FROM course WHERE department='CSE'
);

DELETE FROM instructor
WHERE instructor_name IN ('Test, Alice', 'Test, Bob');

DELETE FROM course
WHERE department = 'CSE';

DELETE FROM department
WHERE department = 'CSE';


-- =========================
-- END OF TEST
-- =========================
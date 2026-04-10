CREATE EXTENSION IF NOT EXISTS vector;
-- ── Tables ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS section (
    section_id  SERIAL          PRIMARY KEY,
    course      VARCHAR(50)     NOT NULL,
    syllabus_url TEXT           NOT NULL
);

CREATE TABLE IF NOT EXISTS syllabus_chunks (
    chunk_id    SERIAL          PRIMARY KEY,
    section_id  INT             NOT NULL REFERENCES section(section_id) ON DELETE CASCADE,
    chunk_text  TEXT            NOT NULL,
    embedding   vector(3072)
);

-- ── Sample data for ISE 201 ───────────────────────────────────────────────────

INSERT INTO section (course, syllabus_url) VALUES
    ('ISE 201', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=84918'),
    ('ISE 201', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=78869'),
    ('ISE 201', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=37772');

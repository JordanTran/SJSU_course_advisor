-- Create database
-- CREATE DATABASE course_advisor;

-- Connect to the database before running the rest:
-- \c course_advisor

-- ── Tables ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS section (
    section_id  SERIAL          PRIMARY KEY,
    course      VARCHAR(50)     NOT NULL,
    syllabus_url TEXT           NOT NULL
);

-- ── Sample data for ISE 201 ───────────────────────────────────────────────────

INSERT INTO section (course, syllabus_url) VALUES
    ('ISE 201', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=84918'),
    ('ISE 201', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=78869'),
    ('ISE 201', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=37772');

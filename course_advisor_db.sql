-- ─────────────────────────────────────────────
--  Requires pgvector extension
-- ─────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────
--  1. DEPARTMENT
-- ─────────────────────────────────────────────
CREATE TABLE department (
    department      VARCHAR(10)  PRIMARY KEY,
    department_name VARCHAR(100) NOT NULL,
    college         VARCHAR(100)
);

-- ─────────────────────────────────────────────
--  2. COURSE
-- ─────────────────────────────────────────────
CREATE TABLE course (
    course_id      SERIAL       PRIMARY KEY,
    department     VARCHAR(10)  NOT NULL,
    catalog_number VARCHAR(10)  NOT NULL,
    course_title   VARCHAR(255) NOT NULL,
    units          SMALLINT     NOT NULL CHECK (units > 0),cd

    UNIQUE (department, catalog_number),

    FOREIGN KEY (department)
        REFERENCES department (department)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ─────────────────────────────────────────────
--  3. INSTRUCTOR
-- ─────────────────────────────────────────────
CREATE TABLE instructor (
    instructor_id   SERIAL       PRIMARY KEY,
    instructor_name VARCHAR(255) NOT NULL UNIQUE
);

-- ─────────────────────────────────────────────
--  4. SECTION
-- ─────────────────────────────────────────────
CREATE TABLE section (
    section_id   SERIAL      PRIMARY KEY,
    course_id     INT         NOT NULL,
    year          SMALLINT    NOT NULL,
    session       VARCHAR(20) NOT NULL,
    section       VARCHAR(10) NOT NULL,
    instructor_id INT         NOT NULL,
    delivery      VARCHAR(50),
    syllabus_url  TEXT,

    UNIQUE (course_id, year, session, section),

    FOREIGN KEY (course_id)
        REFERENCES course (course_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    FOREIGN KEY (instructor_id)
        REFERENCES instructor (instructor_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ─────────────────────────────────────────────
--  5. SYLLABUS CHUNK
-- ─────────────────────────────────────────────
CREATE TABLE syllabus_chunk (
    chunk_id      SERIAL       PRIMARY KEY,
    section_id   INT          NOT NULL,
    chunk_text    TEXT         NOT NULL,
    embedding     vector(3072) NOT NULL,

    FOREIGN KEY (section_id)
        REFERENCES section (section_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

-- ─────────────────────────────────────────────
--  Indexes (TODO)
-- ─────────────────────────────────────────────

-- ─────────────────────────────────────────────
--  Drop NEW tables (in case of partial runs)
-- ─────────────────────────────────────────────
DROP TABLE IF EXISTS syllabus_chunk;
DROP TABLE IF EXISTS section;
DROP TABLE IF EXISTS course;
DROP TABLE IF EXISTS instructor_department;
DROP TABLE IF EXISTS instructor;
DROP TABLE IF EXISTS subject;
DROP TABLE IF EXISTS department;
DROP TABLE IF EXISTS college;

-- ─────────────────────────────────────────────
--  Requires pgvector extension
-- ─────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────
--  1. COLLEGE
-- ─────────────────────────────────────────────

CREATE TABLE college (
    college_id   SERIAL       PRIMARY KEY,
    college_name VARCHAR(100) NOT NULL UNIQUE
);

-- ─────────────────────────────────────────────
--  2. DEPARTMENT
-- ─────────────────────────────────────────────

CREATE TABLE department (
    dept_id      SERIAL       PRIMARY KEY,
    dept_name    VARCHAR(100) NOT NULL UNIQUE,
    college_id   INT          NOT NULL,

    FOREIGN KEY (college_id)
        REFERENCES college (college_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ─────────────────────────────────────────────
--  3. SUBJECT
-- ─────────────────────────────────────────────

CREATE TABLE subject (
    subject      VARCHAR(10)  PRIMARY KEY,
    subject_name VARCHAR(100) NOT NULL,
    dept_id      INT          NOT NULL,

    FOREIGN KEY (dept_id)
        REFERENCES department (dept_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ─────────────────────────────────────────────
--  4. COURSE
-- ─────────────────────────────────────────────

CREATE TABLE course (
    course_id      SERIAL        PRIMARY KEY,
    subject        VARCHAR(10)   NOT NULL,
    catalog_number VARCHAR(10)   NOT NULL,

    UNIQUE (subject, catalog_number),

    FOREIGN KEY (subject)
        REFERENCES subject (subject)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ─────────────────────────────────────────────
--  5. INSTRUCTOR
-- ─────────────────────────────────────────────

CREATE TABLE instructor (
    instructor_id   SERIAL       PRIMARY KEY,
    instructor_name VARCHAR(255) NOT NULL UNIQUE
);

-- ─────────────────────────────────────────────
--  5a. INSTRUCTOR DEPARTMENT (junction)
-- ─────────────────────────────────────────────

CREATE TABLE instructor_department (
    instructor_id INT NOT NULL,
    dept_id       INT NOT NULL,

    PRIMARY KEY (instructor_id, dept_id),

    FOREIGN KEY (instructor_id)
        REFERENCES instructor (instructor_id)
        ON UPDATE CASCADE ON DELETE CASCADE,

    FOREIGN KEY (dept_id)
        REFERENCES department (dept_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ─────────────────────────────────────────────
--  6. SECTION
-- ─────────────────────────────────────────────

CREATE TABLE section (
    section_id    SERIAL        PRIMARY KEY,
    course_id     INT           NOT NULL,
    course_title  VARCHAR(255)  NOT NULL,
    units         NUMERIC(4,2)  NOT NULL CHECK (units > 0),
    year          SMALLINT      NOT NULL,
    session       VARCHAR(20)   NOT NULL,
    section       VARCHAR(10)   NOT NULL,
    instructor_id INT           NOT NULL,
    syllabus_url  TEXT          NOT NULL,
    delivery      VARCHAR(20)   NOT NULL,

    UNIQUE (course_id, year, session, section),

    FOREIGN KEY (course_id)
        REFERENCES course (course_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    FOREIGN KEY (instructor_id)
        REFERENCES instructor (instructor_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ─────────────────────────────────────────────
--  7. SYLLABUS CHUNK
-- ─────────────────────────────────────────────
CREATE TABLE syllabus_chunk (
    chunk_id      SERIAL       PRIMARY KEY,
    section_id    INT          NOT NULL,
    chunk_title   TEXT         NOT NULL,
    chunk_text    TEXT         NOT NULL,
    embedding     vector(768)  NOT NULL,

    FOREIGN KEY (section_id)
        REFERENCES section (section_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

-- ─────────────────────────────────────────────
--  8. INDEXES for Performance Optimization
-- ─────────────────────────────────────────────

-- 1. HNSW for Vector Similarity (Critical for RAG performance)
CREATE INDEX idx_syllabus_embedding_hnsw 
ON syllabus_chunk USING hnsw (embedding vector_cosine_ops);

-- 2. Foreign Keys (Speeds up multi-table JOINs)
CREATE INDEX idx_chunk_section_id ON syllabus_chunk(section_id);
CREATE INDEX idx_section_course_id ON section(course_id);
CREATE INDEX idx_section_instructor_id ON section(instructor_id);

-- 3. Composite Search Index (Speeds up section filtering)
CREATE INDEX idx_section_lookup ON section(year, session, section);
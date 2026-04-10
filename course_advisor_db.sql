CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE courses (
    course_code     VARCHAR(20)     PRIMARY KEY,
    course_title    VARCHAR(300)    NOT NULL
);

CREATE INDEX idx_courses_title_trgm
    ON courses USING gin(course_title gin_trgm_ops);

CREATE TABLE course_codes (
    course_code     VARCHAR(20)     PRIMARY KEY
        REFERENCES courses(course_code) ON DELETE CASCADE,
    subject         VARCHAR(10)     NOT NULL,
    catalog_number  VARCHAR(10)     NOT NULL,
    UNIQUE (subject, catalog_number)
);

CREATE INDEX idx_course_codes_subject ON course_codes(subject);

CREATE TABLE sections (
    section_id      SERIAL          PRIMARY KEY,
    course_code     VARCHAR(20)     NOT NULL
        REFERENCES courses(course_code) ON DELETE CASCADE,
    session         VARCHAR(10)     NOT NULL
        CHECK (session IN ('Fall', 'Spring', 'Summer', 'Winter')),
    year            INT             NOT NULL,
    section         VARCHAR(10)     NOT NULL,
    instructor      VARCHAR(200),
    syllabus_url    TEXT,
    UNIQUE (course_code, session, year, section)
);

CREATE INDEX idx_sections_course     ON sections(course_code);
CREATE INDEX idx_sections_semester   ON sections(session, year);
CREATE INDEX idx_sections_instructor ON sections(instructor);

CREATE TABLE prerequisites (
    course_code     VARCHAR(20)     NOT NULL
        REFERENCES courses(course_code) ON DELETE CASCADE,
    prereq_code     VARCHAR(20)     NOT NULL
        REFERENCES courses(course_code) ON DELETE CASCADE,
    PRIMARY KEY (course_code, prereq_code)
);

CREATE INDEX idx_prereqs_course ON prerequisites(course_code);
CREATE INDEX idx_prereqs_prereq ON prerequisites(prereq_code);

CREATE TABLE IF NOT EXISTS syllabus_chunks (
    chunk_id    SERIAL          PRIMARY KEY,
    section_id  INT             NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    chunk_text  TEXT            NOT NULL,
    embedding   vector(3072)
);

CREATE INDEX idx_chunks_section   ON syllabus_chunks(section_id);
CREATE INDEX idx_chunks_embedding ON syllabus_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

INSERT INTO courses (course_code, course_title) VALUES
    ('ISE 201', 'Introduction to Systems Engineering')
ON CONFLICT DO NOTHING;

INSERT INTO course_codes (course_code, subject, catalog_number) VALUES
    ('ISE 201', 'ISE', '201')
ON CONFLICT DO NOTHING;

INSERT INTO sections (course_code, session, year, section, instructor, syllabus_url) VALUES
    ('ISE 201', 'Fall', 2024, '01', NULL, 'https://sjsu.campusconcourse.com/view_syllabus?course_id=84918'),
    ('ISE 201', 'Fall', 2024, '02', NULL, 'https://sjsu.campusconcourse.com/view_syllabus?course_id=78869'),
    ('ISE 201', 'Fall', 2024, '03', NULL, 'https://sjsu.campusconcourse.com/view_syllabus?course_id=37772')
ON CONFLICT DO NOTHING;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

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
    id              SERIAL          PRIMARY KEY,
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
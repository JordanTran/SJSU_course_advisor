-- Instructor (renamed from Faculty)
CREATE TABLE IF NOT EXISTS Instructor (
    instructor_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

-- Department (kept for future use)
CREATE TABLE Department (
    department_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
);

-- Course
CREATE TABLE IF NOT EXISTS Course (
    course_id SERIAL PRIMARY KEY,
    course_code VARCHAR(20) UNIQUE,
    course_title VARCHAR(255),
    subject VARCHAR(20),
    catalog_number VARCHAR(20),
    department_id INTEGER REFERENCES Department(department_id)
);

-- Syllabus (main scraped data)
CREATE TABLE IF NOT EXISTS Syllabus (
    syllabus_id SERIAL PRIMARY KEY,
    course_id INTEGER REFERENCES Course(course_id),
    instructor_id INTEGER REFERENCES Instructor(instructor_id),
    
    session VARCHAR(20), 
    year INTEGER,
    section VARCHAR(10),
    
    syllabus_url TEXT
);


-- ── Sample data for ISE 201 ───────────────────────────────────────────────────

-- ── Department ─────────────────────────────────────────
INSERT INTO Department (name)
VALUES ('Computer Engineering')
ON CONFLICT DO NOTHING;

-- ── Course ─────────────────────────────────────────────
INSERT INTO Course (course_code, course_title, subject, catalog_number, department_id)
VALUES (
    'ISE 201',
    'Math Foundations for Decision and Data Sciences',
    'ISE',
    '201',
    1
)
ON CONFLICT (course_code) DO NOTHING;

-- ── Instructor ─────────────────────────────────────────
INSERT INTO Instructor (name)
VALUES ('TBD')
ON CONFLICT DO NOTHING;
INSERT INTO Syllabus (course_id, instructor_id, session, year, section, syllabus_url)
VALUES
    (1, 1, 'Fall', 2024, '01', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=84918'),
    (2, 1, 'Fall', 2024, '02', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=78869'),
    (3, 1, 'Fall', 2024, '03', 'https://sjsu.campusconcourse.com/view_syllabus?course_id=37772');

CREATE TABLE Faculty (
    faculty_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);


CREATE TABLE Department (
    department_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    college VARCHAR(100)
);


CREATE TABLE Course (
    course_id VARCHAR(20) PRIMARY KEY,
    course_name VARCHAR(255) NOT NULL,
    subject VARCHAR(20),
    catalog_number VARCHAR(20),
    description TEXT,
    prerequisites TEXT,
    grading_basis VARCHAR(50),
    units NUMERIC,
    department_id INTEGER REFERENCES Department(department_id)
);


CREATE TABLE Syllabus (
    syllabus_id SERIAL PRIMARY KEY,
    course_id VARCHAR(20) REFERENCES Course(course_id),
    faculty_id INTEGER REFERENCES Faculty(faculty_id),
    term VARCHAR(20),
    year INTEGER,
    section VARCHAR(10),
    delivery VARCHAR(50),
    start_date DATE,
    end_date DATE,
    modified_date DATE,
    source_url TEXT,
    raw_text TEXT
);
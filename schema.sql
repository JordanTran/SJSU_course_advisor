-- Instructor (renamed from Faculty)
CREATE TABLE Instructor (
    instructor_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

-- Department (kept for future use)
CREATE TABLE Department (
    department_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    college VARCHAR(100)
);

-- Course
CREATE TABLE Course (
    course_id SERIAL PRIMARY KEY,
    course_code VARCHAR(20) UNIQUE,
    course_title VARCHAR(255),
    subject VARCHAR(20),
    catalog_number VARCHAR(20),
    department_id INTEGER REFERENCES Department(department_id)
);

-- Syllabus (main scraped data)
CREATE TABLE Syllabus (
    syllabus_id SERIAL PRIMARY KEY,
    course_id INTEGER REFERENCES Course(course_id),
    instructor_id INTEGER REFERENCES Instructor(instructor_id),
    
    session VARCHAR(20), 
    year INTEGER,
    section VARCHAR(10),
    
    syllabus_url TEXT
);
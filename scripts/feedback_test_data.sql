-- ─────────────────────────────────────────────
--  Feedback test data — 100,000 rows
--  Run this against your course_advisor database.
--  Expected insert time: ~10-30 seconds.
-- ─────────────────────────────────────────────

-- Sample question and answer banks to produce realistic variety.
-- We cross these with generate_series to reach 100k rows.

DO $$
DECLARE
    questions TEXT[] := ARRAY[
        'What are the grading weights for CS 146?',
        'How many absences are allowed before my grade is affected?',
        'Is there a late submission policy for assignments?',
        'What textbook is required for MATH 161A?',
        'Can I submit homework electronically or does it have to be printed?',
        'What percentage of the grade comes from the final exam?',
        'Are there any group projects in this course?',
        'What is the attendance policy for online sections?',
        'How is academic dishonesty handled in this course?',
        'Does the professor curve grades at the end of the semester?',
        'What programming languages are used in CS 149?',
        'Is the midterm exam open book or closed book?',
        'How many units is BIOL 101?',
        'What are the office hours for Professor Smith?',
        'Is there extra credit available in this course?',
        'What is the prerequisite for CS 151?',
        'How are lab assignments graded in CHEM 1A?',
        'Can I use a calculator on the final exam?',
        'What topics are covered in the first half of the semester?',
        'Is class participation graded?'
    ];

    answers TEXT[] := ARRAY[
        'According to the syllabus, homework is worth 30%, the midterm is worth 30%, and the final exam is worth 40% of your overall grade.',
        'The syllabus states that more than three unexcused absences will result in a one-letter-grade deduction. After six absences your case may be referred to the dean.',
        'Late submissions are accepted up to 48 hours after the deadline with a 10% penalty per day. Work submitted more than 48 hours late will receive a zero.',
        'The required textbook is listed as Introduction to Mathematical Statistics, 8th edition, by Hogg, McKean, and Craig. A PDF is available through the SJSU library.',
        'All homework must be submitted through Canvas as a PDF. Handwritten work should be scanned. Emailed submissions are not accepted.',
        'The final exam accounts for 35% of your final grade. You must score at least 60% on the final to pass the course regardless of your overall average.',
        'Yes, there is one group project worth 20% of your grade. Groups of three to four students will be formed during the third week of class.',
        'Online sections require synchronous attendance via Zoom. Recordings are provided for review but do not substitute for live attendance, which is tracked.',
        'Any instance of academic dishonesty will result in a zero on the assignment and will be reported to the Office of Student Conduct. A second offense may result in course failure.',
        'The syllabus does not mention any grade curving. Final letter grades are assigned based on fixed thresholds: 90% and above is an A, 80–89% is a B, and so on.',
        'CS 149 uses Java as the primary language. Students are expected to have prior experience with Python or C++ from the prerequisite course.',
        'Both the midterm and final are closed book and closed notes. One double-sided handwritten cheat sheet is permitted for the final exam only.',
        'BIOL 101 is a 3-unit lecture course. Students who also enroll in BIOL 101L receive an additional 1 unit for the lab component.',
        'Office hours are held Tuesdays and Thursdays from 2:00 PM to 3:30 PM in MH 213. Virtual office hours via Zoom are available by appointment.',
        'There is no extra credit offered in this course. The instructor encourages students to focus on the regular assignments instead.',
        'The prerequisite for CS 151 is CS 46B with a grade of C or better, or instructor consent. Students without the prerequisite will be administratively dropped.',
        'Lab reports are graded on accuracy of results, quality of analysis, and proper citation of methods. Each lab is worth 5 points toward the final grade.',
        'Calculators are not permitted on the final exam. All required calculations are designed to be completed by hand within the allotted time.',
        'The first half of the semester covers linear algebra foundations, probability theory, and descriptive statistics. See the schedule on Canvas for exact dates.',
        'Class participation accounts for 10% of your grade and is assessed through in-class polls, discussion questions, and occasional cold-calling.'
    ];

    session_prefixes TEXT[] := ARRAY[
        'a1b2c3d4', 'e5f6a7b8', 'c9d0e1f2', 'a3b4c5d6', 'e7f8a9b0',
        'c1d2e3f4', 'a5b6c7d8', 'e9f0a1b2', 'c3d4e5f6', 'a7b8c9d0',
        'f1e2d3c4', 'b5a6f7e8', 'd9c0b1a2', 'f3e4d5c6', 'b7a8f9e0',
        'd1c2b3a4', 'f5e6d7c8', 'b9a0f1e2', 'd3c4b5a6', 'f7e8d9c0'
    ];

    i INT;
    q_idx INT;
    a_idx INT;
    s_idx INT;
    fake_session_id TEXT;
    fake_created_at TIMESTAMPTZ;
BEGIN
    FOR i IN 1..100000 LOOP
        q_idx := (i % array_length(questions, 1)) + 1;
        a_idx := (i % array_length(answers,   1)) + 1;
        s_idx := (i % array_length(session_prefixes, 1)) + 1;

        -- Build a fake UUID-shaped session id. Each prefix maps to ~5000 rows,
        -- giving realistic cardinality without being completely unique.
        fake_session_id := session_prefixes[s_idx]
            || '-' || lpad((i % 9999)::TEXT, 4, '0')
            || '-4' || lpad((i % 999)::TEXT,  3, '0')
            || '-' || lpad((i % 9999)::TEXT, 4, '0')
            || '-' || lpad(i::TEXT, 12, '0');

        -- Spread rows over the past two years so ORDER BY created_at is meaningful.
        fake_created_at := now() - (random() * interval '730 days');

        INSERT INTO feedback (session_id, question, answer, is_positive, created_at)
        VALUES (
            fake_session_id,
            questions[q_idx],
            answers[a_idx],
            (i % 3 != 0),   -- roughly 67% positive, 33% negative
            fake_created_at
        );
    END LOOP;
END $$;

-- ─────────────────────────────────────────────
--  Verify
-- ─────────────────────────────────────────────
SELECT
    COUNT(*)                                AS total,
    COUNT(*) FILTER (WHERE is_positive)     AS positive,
    COUNT(*) FILTER (WHERE NOT is_positive) AS negative,
    MIN(created_at)::DATE                   AS earliest,
    MAX(created_at)::DATE                   AS latest
FROM feedback;

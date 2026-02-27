from course_advisor import CourseAdvisor

SYLLABUS_URLS = [
    "https://sjsu.campusconcourse.com/view_syllabus?course_id=84918",
    "https://sjsu.campusconcourse.com/view_syllabus?course_id=78869",
    "https://sjsu.campusconcourse.com/view_syllabus?course_id=37772",
    # add more URLs as needed...
]

if __name__ == "__main__":
    advisor = CourseAdvisor(syllabus_urls=SYLLABUS_URLS)
    advisor.chat()

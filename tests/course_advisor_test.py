import sys
import os
 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
 
from dotenv import load_dotenv
from course_advisor import CourseAdvisor
load_dotenv()
 
def test_course_advisor():
    advisor = CourseAdvisor()
    questions = [
        "What is the grading breakdown for this course?",
        "What is the AI policy?",
        "When is the project proposal due?",
    ]
    for q in questions:
        print(f"Q: {q}")
        print(f"A: {advisor.ask(q, course_name='ISE 201')}\n")
 
 
if __name__ == "__main__":
    test_course_advisor()
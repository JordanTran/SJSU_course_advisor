import asyncio
import sys
import os
 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
 
from dotenv import load_dotenv
from course_advisor import CourseAdvisor
 
load_dotenv()
 
 
async def test_course_advisor():
    advisor = CourseAdvisor()
    await advisor.setup()
    try:
        questions = [
            "What is the grading breakdown for this course?",
            "What is the AI policy?",
            "When is the project proposal due?",
        ]
        for q in questions:
            print(f"Q: {q}")
            answer = await advisor.ask(q, course_name="ISE 201")
            print(f"A: {answer}\n")
    finally:
        await advisor.close()
 
 
if __name__ == "__main__":
    asyncio.run(test_course_advisor())

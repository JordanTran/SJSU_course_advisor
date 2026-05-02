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
        question = "What topics are covered in CMPE 180B? How are you assessed? Is there a project?"

        print(f"Q: {question}")
        await advisor.ask(question, verbose=True)
    finally:
        await advisor.close()


if __name__ == "__main__":
    asyncio.run(test_course_advisor())

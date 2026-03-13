# course_advisor
# 1. Install
pip install -r requirements.txt

# 2. Configure
Set your DB_PASSWORD and GOOGLE_API_KEY in .env file

# 3. Run Server
uvicorn course_advisor_api:app --reload --env-file .env

# 4. Open Browser
open http://localhost:8000 in your browser

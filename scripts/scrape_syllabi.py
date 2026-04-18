"""
Setup:
    pip install playwright pandas
    playwright install chromium
 
Run:
    python3 scrape_syllabi.py
"""

import re
import time
import random
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

YEARS = [2025, 2026]
BASE_URL = "https://sjsu.campusconcourse.com"
START_URLS = [
    f"{BASE_URL}/search?search_performed=1&sort_by=credits&year={year}&template=non"
    for year in YEARS
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

SCRAPE_COLUMNS = [
    "subject",
    "catalog_number",
    "course_title",
    "units",
    "instructor_name",
    "year",
    "session",
    "section",
    "syllabus_url",
]

DEPT_NAMES = {
    'AAS' : 'Sociology & Interdisciplinary Social Sciences',
    'ADV' : 'Journalism/Mass Communications',
    'AE' : 'Aerospace Engineering',
    'AFAM' : 'African American Studies',
    'AMS' : 'Humanities',
    'ANI' : 'Design',
    'ANTH' : 'Anthropology',
    'ARED' : 'Art & Art History',
    'ART' : 'Art & Art History',
    'ARTH' : 'Art & Art History',
    'AS' : 'Aerospace Studies',
    'ASTR' : 'Physics & Astronomy',
    'ATH' : 'Athletics',
    'AUD' : 'Audiology',
    'AVIA' : 'Aviation',
    'BIOL' : 'Biological Sciences',
    'BME' : 'Biomedical Engineering',
    'BOT' : 'Biological Sciences',
    'BUS' : 'Graduate School of Business',
    'BUS1' : 'Accounting & Finance',
    'BUS2' : 'Marketing & Business Analytics',
    'BUS3' : 'Management',
    'BUS4' : 'Information Systems & Technology',
    'BUS5' : 'Global Innovation & Leadership',
    'CA' : 'Humanities',
    'CCS' : 'Chicana & Chicano Studies',
    'CE' : 'Civil & Environmental Engineering',
    'CHAD' : 'Child & Adolescent Development',
    'CHE' : 'Chemical & Materials Engineering',
    'CHEM' : 'Chemistry',
    'CHIN' : 'World Languages & Literatures',
    'CMPE' : 'Computer Engineering',
    'COLT' : 'English & Comparative Literature',
    'COMM' : 'Communication Studies',
    'CS' : 'Computer Science',
    'DANC' : 'Music & Dance',
    'DATA' : 'Applied Data Science',
    'DSGD' : 'Design',
    'DSGN' : 'Design',
    'DSID' : 'Design',
    'DSIT' : 'Design',
    'ECON' : 'Economics',
    'EDAU' : 'Communicative Disorders & Sciences',
    'EDCO' : 'Counselor Education',
    'EDD' : 'Ed.D Educational Leadership',
    'EDEL' : 'Teacher Education',
    'EDLD' : 'Educational Leadership',
    'EDSC' : 'Teacher Education',
    'EDSE' : 'Special Education',
    'EDSP' : 'Communicative Disorders & Sciences',
    'EDTE' : 'Teacher Education',
    'EDUC' : 'College of EDUC',
    'EE' : 'Electrical Engineering',
    'ENED' : 'English & Comparative Literature',
    'ENGL' : 'English & Comparative Literature',
    'ENGR' : 'Interdisciplinary Engineering',
    'ENT' : 'Biological Sciences',
    'ENVS' : 'Environmental Studies',
    'ESM' : 'Undergraduate Studies',
    'FLED' : 'World Languages & Literatures',
    'FORL' : 'World Languages & Literatures',
    'FREN' : 'World Languages & Literatures',
    'FS' : 'Justice Studies',
    'GEOG' : 'School of Planning, Policy, and Environmental Studies',
    'GEOL' : 'Geology',
    'GERM' : 'World Languages & Literatures',
    'GERO' : 'Social Work',
    'GISC' : 'School of Planning, Policy, and Environmental Studies',
    'GLST' : 'School of Planning, Policy, and Environmental Studies',
    'HA' : 'College of H&A',
    'HEBR' : 'World Languages & Literatures',
    'HIST' : 'History',
    'HS' : 'Department of Public Health',
    'HSPM' : 'Hospitality, Tourism & Event Management',
    'HUM' : 'Humanities',
    'IDT' : 'School of Information',
    'INFM' : 'School of Information',
    'INFO' : 'School of Information',
    'ISDA' : 'School of Information',
    'ISE' : 'Industrial & Systems Engineering',
    'ITAL' : 'World Languages & Literatures',
    'JOUR' : 'Journalism/Mass Communications',
    'JPN' : 'World Languages & Literatures',
    'JS' : 'Justice Studies',
    'JWSS' : 'History',
    'KIN' : 'Kinesiology',
    'KNED' : 'Kinesiology',
    'LING' : 'Linguistics & Language Development',
    'LLD' : 'Linguistics & Language Development',
    'LSTP' : 'Humanities',
    'MARA' : 'School of Information',
    'MATE' : 'Chemical & Materials Engineering',
    'MATH' : 'Mathematics & Statistics',
    'MCOM' : 'Journalism/Mass Communications',
    'MDES' : 'Humanities',
    'ME' : 'Mechanical Engineering',
    'METR' : 'Meteorology & Climate Science',
    'MICR' : 'Biological Sciences',
    'MILS' : 'Military Science',
    'MS' : 'Moss Landing Marine Lab',
    'MTED' : 'Mathematics & Statistics',
    'MTM' : 'Graduate School of Business',
    'MUED' : 'Music & Dance',
    'MUSC' : 'Music & Dance',
    'NAIS' : 'Sociology & Interdisciplinary Social Sciences',
    'NUCS' : 'Chemistry',
    'NUFS' : 'Nutrition, Food Science & Packaging',
    'NURS' : 'Nursing',
    'OCTH' : 'Occupational Therapy',
    'ORGS' : 'Anthropology',
    'PADM' : 'School of Planning, Policy, and Environmental Studies',
    'PH' : 'Department of Public Health',
    'PHIL' : 'Philosophy',
    'PHOT' : 'Art & Art History',
    'PHYS' : 'Physics & Astronomy',
    'PKG' : 'Nutrition, Food Science & Packaging',
    'POLS' : 'Political Science',
    'PORT' : 'World Languages & Literatures',
    'PR' : 'Journalism/Mass Communications',
    'PSYC' : 'Psychology',
    'RECL' : 'Department of Public Health',
    'RELS' : 'Humanities',
    'RTVF' : 'Film & Theatre',
    'RUSS' : 'World Languages & Literatures',
    'SCED' : 'Science Education',
    'SCI' : 'College of SCI',
    'SCWK' : 'Social Work',
    'SMPD' : 'Medical Product Development Management',
    'SOCI' : 'Sociology & Interdisciplinary Social Sciences',
    'SOCS' : 'History',
    'SPAN' : 'World Languages & Literatures',
    'SSCI' : 'College of SocSci',
    'SSED' : 'History',
    'STAT' : 'Psychology',
    'TA' : 'Film & Theatre',
    'TAG' : 'World Languages & Literatures',
    'TECH' : 'Technology',
    'UNVS' : 'Undergraduate Studies',
    'URBP' : 'School of Planning, Policy, and Environmental Studies',
    'VIET' : 'World Languages & Literatures',
    'WGSS' : 'Sociology & Interdisciplinary Social Sciences',
    'ZOOL' : 'Biological Sciences'
}

SUBJECT_NAMES = {
    'AAS' : 'Asian American Studies',
    'ADV' : 'Advertising',
    'AE' : 'Aerospace Engineering',
    'AFAM' : 'African American Studies',
    'AMS' : 'American Studies',
    'ANI' : 'Animation',
    'ANTH' : 'Anthropology',
    'ARED' : 'Art Education',
    'ART' : 'Art',
    'ARTH' : 'Art History',
    'AS' : 'Aerospace Studies',
    'ASTR' : 'Astronomy',
    'ATH' : 'Athletics (Intercollegiate)',
    'AUD' : 'Audiology',
    'AVIA' : 'Aviation',
    'BIOL' : 'Biological Sciences',
    'BME' : 'Biomedical Engineering',
    'BOT' : 'Botany',
    'BUS' : 'Business - Graduate Level',
    'BUS1' : 'Business - Accounting and Finance',
    'BUS2' : 'Business - Marketing & Business Analytics',
    'BUS3' : 'Business - Management',
    'BUS4' : 'Business - Information Systems & Technology',
    'BUS5' : 'Business - Global Innovation & Leadership',
    'CA' : 'Creative Arts',
    'CCS' : 'Chicana and Chicano Studies',
    'CE' : 'Civil and Environmental Engineering',
    'CHAD' : 'Child and Adolescent Development',
    'CHE' : 'Chemical Engineering',
    'CHEM' : 'Chemistry',
    'CHIN' : 'Chinese',
    'CMPE' : 'Computer Engineering',
    'COLT' : 'Comparative Literature',
    'COMM' : 'Communication Studies',
    'CS' : 'Computer Science',
    'DANC' : 'Dance',
    'DATA' : 'Data Analytics',
    'DSGD' : 'Graphic Design',
    'DSGN' : 'Design',
    'DSID' : 'Industrial Design',
    'DSIT' : 'Interior Design',
    'ECON' : 'Economics',
    'EDAU' : 'Audiology',
    'EDCO' : 'Counselor Education',
    'EDD' : 'Ed.D Leadership Program',
    'EDEL' : 'Elementary Education',
    'EDLD' : 'Educational Leadership',
    'EDSC' : 'Secondary Education',
    'EDSE' : 'Special Education',
    'EDSP' : 'Speech Pathology',
    'EDTE' : 'Teacher Education',
    'EDUC' : 'Education',
    'EE' : 'Electrical Engineering',
    'ENED' : 'English Education',
    'ENGL' : 'English',
    'ENGR' : 'Interdisciplinary Engineering',
    'ENT' : 'Entomology',
    'ENVS' : 'Environmental Studies',
    'ESM' : 'Early Start Program Math',
    'FLED' : 'Foreign Language Education',
    'FORL' : 'Foreign Languages',
    'FREN' : 'French',
    'FS' : 'Forensic Science',
    'GEOG' : 'Geography',
    'GEOL' : 'Geology',
    'GERM' : 'German',
    'GERO' : 'Gerontology',
    'GISC' : 'Geographic Information Science',
    'GLST' : 'Global Studies',
    'HA' : 'Humanities & the Arts',
    'HEBR' : 'Hebrew',
    'HIST' : 'History',
    'HS' : 'Health Science',
    'HSPM' : 'Business - Hospitality, Tourism and Event Management',
    'HUM' : 'Humanities',
    'IDT' : 'Instructional Design and Technnology',
    'INFM' : 'Informatics',
    'INFO' : 'Information',
    'ISDA' : 'Information Science and Data Analytics',
    'ISE' : 'Industrial and Systems Engineering',
    'ITAL' : 'Italian',
    'JOUR' : 'Journalism',
    'JPN' : 'Japanese',
    'JS' : 'Justice Studies',
    'JWSS' : 'Jewish Studies',
    'KIN' : 'Activity/Physical Education Classes',
    'KNED' : 'Kinesiology',
    'LING' : 'Linguistics',
    'LLD' : 'Linguistics & Language Development',
    'LSTP' : 'Liberal Studies Teacher Prep',
    'MARA' : 'Master Archives and Records Administration',
    'MATE' : 'Materials Engineering',
    'MATH' : 'Mathematics and Statistics',
    'MCOM' : 'Mass Communication',
    'MDES' : 'Middle East Studies',
    'ME' : 'Mechanical Engineering',
    'METR' : 'Meteorology and Climate Science',
    'MICR' : 'Microbiology',
    'MILS' : 'Military Science',
    'MS' : 'Marine Science',
    'MTED' : 'Mathematics Education',
    'MTM' : 'Transportation Management',
    'MUED' : 'Music Education',
    'MUSC' : 'Music',
    'NAIS' : 'Native American and Indigenous Studies',
    'NUCS' : 'Nuclear Science',
    'NUFS' : 'Nutrition and Food Science',
    'NURS' : 'Nursing',
    'OCTH' : 'Occupational Therapy',
    'ORGS' : 'Organizational Studies',
    'PADM' : 'Public Administration',
    'PH' : 'Public Health',
    'PHIL' : 'Philosophy',
    'PHOT' : 'Photography',
    'PHYS' : 'Physics',
    'PKG' : 'Packaging',
    'POLS' : 'Political Science',
    'PORT' : 'Portuguese',
    'PR' : 'Public Relations',
    'PSYC' : 'Psychology',
    'RECL' : 'Recreation',
    'RELS' : 'Religious Studies',
    'RTVF' : 'Radio - Television - Film',
    'RUSS' : 'Russian',
    'SCED' : 'Science Education',
    'SCI' : 'Science',
    'SCWK' : 'Social Work',
    'SMPD' : 'Medical Product Development Management',
    'SOCI' : 'Sociology',
    'SOCS' : 'Social Science',
    'SPAN' : 'Spanish',
    'SSCI' : 'Social Science',
    'SSED' : 'Social Science Education',
    'STAT' : 'Statistics',
    'TA' : 'Theatre Arts',
    'TAG' : 'Tagalog',
    'TECH' : 'Technology',
    'UNVS' : 'University Studies',
    'URBP' : 'Urban and Regional Planning',
    'VIET' : 'Vietnamese',
    'WGSS' : 'Women, Gender and Sexuality Studies',
    'ZOOL' : 'Zoology'
}

SUBJECT_COLLEGES = {
    'AAS' : 'College of Social Sciences',
    'ADV' : 'College of Humanities and the Arts',
    'AE' : 'Charles W Davidson College of Engineering',
    'AFAM' : 'College of Social Sciences',
    'AMS' : 'College of Humanities and the Arts',
    'ANI' : 'College of Humanities and the Arts',
    'ANTH' : 'College of Social Sciences',
    'ARED' : 'College of Humanities and the Arts',
    'ART' : 'College of Humanities and the Arts',
    'ARTH' : 'College of Humanities and the Arts',
    'AS' : 'College of Health and Human Sciences',
    'ASTR' : 'College of Science',
    'ATH' : 'Athletics',
    'AUD' : 'College of Health and Human Sciences',
    'AVIA' : 'Charles W Davidson College of Engineering',
    'BIOL' : 'College of Science',
    'BME' : 'Charles W Davidson College of Engineering',
    'BOT' : 'College of Science',
    'BUS' : 'Lucas College and Graduate School of Business',
    'BUS1' : 'Lucas College and Graduate School of Business',
    'BUS2' : 'Lucas College and Graduate School of Business',
    'BUS3' : 'Lucas College and Graduate School of Business',
    'BUS4' : 'Lucas College and Graduate School of Business',
    'BUS5' : 'Lucas College and Graduate School of Business',
    'CA' : 'College of Humanities and the Arts',
    'CCS' : 'College of Social Sciences',
    'CE' : 'Charles W Davidson College of Engineering',
    'CHAD' : 'Connie L Lurie College of Educatio',
    'CHE' : 'Charles W Davidson College of Engineering',
    'CHEM' : 'College of Science',
    'CHIN' : 'College of Humanities and the Arts',
    'CMPE' : 'Charles W Davidson College of Engineering',
    'COLT' : 'College of Humanities and the Arts',
    'COMM' : 'College of Social Sciences',
    'CS' : 'College of Science',
    'DANC' : 'College of Humanities and the Arts',
    'DATA' : 'College of Information, Data and Society',
    'DSGD' : 'College of Humanities and the Arts',
    'DSGN' : 'College of Humanities and the Arts',
    'DSID' : 'College of Humanities and the Arts',
    'DSIT' : 'College of Humanities and the Arts',
    'ECON' : 'College of Social Sciences',
    'EDAU' : 'Connie L Lurie College of Education',
    'EDCO' : 'Connie L Lurie College of Education',
    'EDD' : 'Connie L Lurie College of Education',
    'EDEL' : 'Connie L Lurie College of Education',
    'EDLD' : 'Connie L Lurie College of Education',
    'EDSC' : 'Connie L Lurie College of Education',
    'EDSE' : 'Connie L Lurie College of Education',
    'EDSP' : 'Connie L Lurie College of Education',
    'EDTE' : 'Connie L Lurie College of Education',
    'EDUC' : 'Connie L Lurie College of Education',
    'EE' : 'Charles W Davidson College of Engineering',
    'ENED' : 'College of Humanities and the Arts',
    'ENGL' : 'College of Humanities and the Arts',
    'ENGR' : 'Charles W Davidson College of Engineering',
    'ENT' : 'College of Science',
    'ENVS' : 'College of Social Sciences',
    'ESM' : 'University Studies',
    'FLED' : 'College of Humanities and the Arts',
    'FORL' : 'College of Humanities and the Arts',
    'FREN' : 'College of Humanities and the Arts',
    'FS' : 'College of Social Sciences',
    'GEOG' : 'College of Social Sciences',
    'GEOL' : 'College of Science',
    'GERM' : 'College of Humanities and the Arts',
    'GERO' : 'College of Health and Human Sciences',
    'GISC' : 'College of Social Sciences',
    'GLST' : 'College of Social Sciences',
    'HA' : 'College of Humanities and the Arts',
    'HEBR' : 'College of Humanities and the Arts',
    'HIST' : 'College of Social Sciences',
    'HS' : 'College of Health and Human Sciences',
    'HSPM' : 'Lucas College and Graduate School of Business',
    'HUM' : 'College of Humanities and the Arts',
    'IDT' : 'College of Information, Data and Society',
    'INFM' : 'College of Information, Data and Society',
    'INFO' : 'College of Information, Data and Society',
    'ISDA' : 'College of Information, Data and Society',
    'ISE' : 'Charles W Davidson College of Engineering',
    'ITAL' : 'College of Humanities and the Arts',
    'JOUR' : 'College of Humanities and the Arts',
    'JPN' : 'College of Humanities and the Arts',
    'JS' : 'College of Social Sciences',
    'JWSS' : 'College of Social Sciences',
    'KIN' : 'College of Health and Human Sciences',
    'KNED' : 'College of Health and Human Sciences',
    'LING' : 'College of Humanities and the Arts',
    'LLD' : 'College of Humanities and the Arts',
    'LSTP' : 'College of Humanities and the Arts',
    'MARA' : 'College of Information, Data and Society',
    'MATE' : 'Charles W Davidson College of Engineering',
    'MATH' : 'College of Science',
    'MCOM' : 'College of Humanities and the Arts',
    'MDES' : 'College of Humanities and the Arts',
    'ME' : 'Charles W Davidson College of Engineering',
    'METR' : 'College of Science',
    'MICR' : 'College of Science',
    'MILS' : 'College of Health and Human Sciences',
    'MS' : 'College of Science',
    'MTED' : 'College of Science',
    'MTM' : 'Lucas College and Graduate School of Business',
    'MUED' : 'College of Humanities and the Arts',
    'MUSC' : 'College of Humanities and the Arts',
    'NAIS' : 'College of Social Sciences',
    'NUCS' : 'College of Science',
    'NUFS' : 'College of Health and Human Sciences',
    'NURS' : 'College of Health and Human Sciences',
    'OCTH' : 'College of Health and Human Sciences',
    'ORGS' : 'College of Social Sciences',
    'PADM' : 'College of Social Sciences',
    'PH' : 'College of Health and Human Sciences',
    'PHIL' : 'College of Humanities and the Arts',
    'PHOT' : 'College of Humanities and the Arts',
    'PHYS' : 'College of Science',
    'PKG' : 'College of Health and Human Sciences',
    'POLS' : 'College of Social Sciences',
    'PORT' : 'College of Humanities and the Arts',
    'PR' : 'College of Humanities and the Arts',
    'PSYC' : 'College of Social Sciences',
    'RECL' : 'College of Health and Human Sciences',
    'RELS' : 'College of Humanities and the Arts',
    'RTVF' : 'College of Humanities and the Arts',
    'RUSS' : 'College of Humanities and the Arts',
    'SCED' : 'College of Science',
    'SCI' : 'College of Science',
    'SCWK' : 'College of Health and Human Sciences',
    'SMPD' : 'College of Science',
    'SOCI' : 'College of Social Sciences',
    'SOCS' : 'College of Social Sciences',
    'SPAN' : 'College of Humanities and the Arts',
    'SSCI' : 'College of Social Sciences',
    'SSED' : 'College of Social Sciences',
    'STAT' : 'College of Social Sciences',
    'TA' : 'College of Humanities and the Arts',
    'TAG' : 'College of Humanities and the Arts',
    'TECH' : 'Charles W Davidson College of Engineering',
    'UNVS' : 'University Studies',
    'URBP' : 'College of Social Sciences',
    'VIET' : 'College of Humanities and the Arts',
    'WGSS' : 'College of Social Sciences',
    'ZOOL' : 'College of Science'
}

# ── context factory ────────────────────────────────────────────────────────────

def new_context(browser, ua_index: int = 0):
    return browser.new_context(
        user_agent=USER_AGENTS[ua_index % len(USER_AGENTS)]
    )


# ── pass 1: collect rows from search-result pages ─────────────────────────────

def collect_search_rows(page) -> list[dict]:
    """Parse the current search-results page; return one dict per row."""
    rows = []
    try:
        page.wait_for_selector("tbody tr", timeout=20_000)
    except PWTimeout:
        print("  [timeout waiting for results]")
        return rows

    for tr in page.query_selector_all("tbody tr"):
        # 1. Capture and Clean Course Title
        a = tr.query_selector("h3 a, h4 a, h5 a, .h5 a")
        if not a:
            continue

        raw_title = (a.inner_text() or "").strip()

        # Check for section in title and clean it regardless of priority
        section_in_title = None
        match_section = re.search(r"\s+Section\s+(\d+)", raw_title, re.I)
        if match_section:
            section_in_title = [int(match_section.group(1))]
            course_title = re.sub(r"\s+Section\s+\d+", "", raw_title, flags=re.I).strip()
        else:
            course_title = raw_title

        href = a.get_attribute("href") or ""
        syllabus_url = href if href.startswith("http") else BASE_URL + "/" + href.lstrip("/")

        if re.search(r"template", course_title, re.I):
            continue

        # 2. Parse Columns
        cols = [c.inner_text().strip() for c in tr.query_selector_all("div.col-sm-3")]
        while len(cols) < 4:
            cols.append("")

        # 3. Handle Section Priority
        section_from_col = [int(m.group()) for m in re.finditer(r"\d+", cols[2])]
        section = section_from_col if section_from_col else section_in_title

        credits = None
        credit_td = tr.query_selector("td.align-bottom")
        if credit_td:
            m_credits = re.search(r"([\d.]+)", credit_td.inner_text())
            if m_credits:
                credits = float(m_credits.group(1))

        subject = ""
        catalog_number = ""
        m = re.match(r"([A-Z0-9]+)-(\w+)", cols[0], re.I)
        if m:
            subject = m.group(1).upper()
            catalog_number = m.group(2).upper()

        session = next((s for s in ("Spring", "Fall", "Summer", "Winter") if s in cols[1]), "")
        m2 = re.search(r"\b(20\d{2})\b", cols[1])
        year = int(m2.group(1)) if m2 else ""
        instructor_name = cols[3]
        if instructor_name == ',':
            continue

        if not all([subject, catalog_number, course_title, instructor_name, year, session, section, credits, syllabus_url]):
            continue

        rows.append({
            "subject":         subject,
            "catalog_number":  catalog_number,
            "course_title":    course_title,
            "instructor_name": instructor_name,
            "year":            year,
            "session":         session,
            "section":         section,
            "units":           credits,
            "syllabus_url":    syllabus_url,
        })
    return rows


def click_next(page) -> bool:
    """Advance to the next search-results page via JS form submit."""
    try:
        btn = page.query_selector("button:has-text('Next'), button:has-text('next')")
        if not btn:
            print("  [click_next] No Next button found in DOM")
            return False
        onclick = btn.get_attribute("onclick") or ""
        # handle both val(227) and val('227')
        m = re.search(r"#offset.*?val\(['\"]?(\d+)['\"]?\)", onclick)
        if not m:
            print(f"  [click_next] Regex didn't match onclick: {repr(onclick)}")
            return False
        offset = m.group(1)
        page.evaluate(
            f"() => {{ $('#offset').val({offset}); $('#search_form').trigger('submit'); }}"
        )
        page.wait_for_selector("tbody tr", timeout=15_000)
        time.sleep(random.uniform(2, 5))  # randomised delay instead of fixed 1s
        return True
    except PWTimeout:
        print("  [click_next] Timeout waiting for next page to load")
        return False
    except Exception as e:
        print(f"  [click_next] Unexpected error: {e}")
        return False


# ── save to CSV ────────────────────────────────────────────────────────────────

def save_csv(rows: list[dict], path: str = "cmpe_syllabi_db.csv"):
    if not rows:
        print("\nNo data scraped — nothing saved.")
        return

    df = pd.DataFrame(rows, columns=SCRAPE_COLUMNS)
    df = df.explode("section").reset_index(drop=True)
    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].astype(str)
    df[str_cols] = df[str_cols].apply(lambda col: col.str.strip())
    df['dept_name'] = df['subject'].map(DEPT_NAMES)
    df['subject_name'] = df['subject'].map(SUBJECT_NAMES)
    df['college_name'] = df['subject'].map(SUBJECT_COLLEGES)
    df = df.dropna()
    df = df.drop_duplicates(subset=['subject', 'catalog_number', 'year', 'session', 'section'])
    df.to_csv(path, index=False)

    print(f"\n{'─'*50}")
    print(f"  Saved : {path}")
    print(f"  Rows  : {len(df)}")
    if not df['year'].empty:
        print(f"  Years : {df['year'].max()} → {df['year'].min()}")
    print(f"{'─'*50}\n")
    print(df.head(10).to_string())


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    all_rows: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ua_index = 0
        context = new_context(browser, ua_index)
        page = context.new_page()

        print(f"\nPass 1 — collecting search results …\n")
        pg = 1

        for current_year, url in zip(YEARS, START_URLS):
            m_offset = re.search(r"offset=(\d+)", url)
            current_offset = int(m_offset.group(1)) if m_offset else 0

            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
            print(f"Year: {current_year} (starting offset: {current_offset})")

            while True:
                print(f"  Page {pg} (offset {current_offset}) … ", end="", flush=True)
                rows = collect_search_rows(page)
                all_rows.extend(rows)
                print(f"{len(rows)} rows  (total: {len(all_rows)})")

                # ── capture next offset BEFORE anything else ──────────────────
                btn = page.query_selector("button:has-text('Next')")
                if btn:
                    onclick = btn.get_attribute("onclick") or ""
                    m = re.search(r"val\(['\"]?(\d+)['\"]?\)", onclick)
                    if m:
                        current_offset = int(m.group(1))

                # ── small cooldown every 50 pages (skip on hard reset pages) ──
                if pg % 50 == 0 and pg % 200 != 0:
                    cooldown = random.uniform(120, 180)
                    print(f"  Cooldown at page {pg} — sleeping {cooldown:.0f}s")
                    time.sleep(cooldown)

                # ── hard reset every 200 pages ────────────────────────────────
                if pg % 200 == 0:
                    print(f"  Hard reset at page {pg} — sleeping 120s + restarting context")
                    time.sleep(120)
                    context.close()
                    ua_index += 1
                    context = new_context(browser, ua_index)
                    page = context.new_page()
                    resume_url = (
                        f"{BASE_URL}/search?search_performed=1"
                        f"&offset={current_offset}"
                        f"&sort_by=credits"
                        f"&year={current_year}"
                        f"&template=non"
                    )
                    print(f"  Resuming at: {resume_url}")
                    page.goto(resume_url, wait_until="domcontentloaded", timeout=30_000)
                    time.sleep(2)
                    pg += 1
                    continue  # skip click_next — already on the right page

                if not click_next(page):
                    print("  No Next button — search complete for this year.")
                    break

                pg += 1
        browser.close()

    save_csv(all_rows)


if __name__ == "__main__":
    main()
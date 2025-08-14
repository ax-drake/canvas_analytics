import requests
import re
import csv
import time
from datetime import datetime

# === START TIME ===
print(f"[BEGIN] Started Process at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# === DRY RUN ===
DRY_RUN = False # Set to False to run full export

# === CONFIGURATION ===
ACCESS_TOKEN = '3785~xJ6DztZ6739TCnxAue6Ba46QRVnfQX9EKGW6zk2u6DrZwYZxuWRzCBPVyJ8PaKyY'
API_BASE_URL = 'https://su.instructure.com/api/v1'
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

# === CACHING LAYER ===
term_cache = {}

# === GET COURSE IDS ===
def fetch_course_ids(account_id="1"):
    course_ids = []
    coll_course_ids = []
    url = f"{API_BASE_URL}/accounts/{account_id}/courses"
    base_params = {
        "per_page": 100,
        "enrollment_term_id": 379,
        "state[]": ["available"],
        "include[]": ["term"]
    }
    page = 1
    first_request = True

    while url:
        print(f"[FETCH] Requesting page {page} of courses...")

        if first_request:
            response = requests.get(url, headers=HEADERS, params=base_params, timeout=10)
            first_request = False
        else:
            response = requests.get(url, headers=HEADERS, timeout=10)

        response.raise_for_status()
        courses = response.json()
        print(f"[FETCHED] Retrieved {len(courses)} courses from page {page}")
        course_ids.extend([course["id"] for course in courses])
        url = response.links.get("next", {}).get("url")
        page += 1

    print(f"[COMPLETE] Total courses fetched: {len(course_ids)}")
    return course_ids

#COURSE_IDS = fetch_course_ids(account_id="1")
SUBACCOUNT_ID = "54"  # Replace with your actual subaccount ID
print(f"[INFO] Fetching courses from subaccount {SUBACCOUNT_ID}")

COURSE_IDS = fetch_course_ids(account_id=SUBACCOUNT_ID)

# === GET TRUNCATED COURSE NAME ===
def extract_truncated_course_id(course_name):
    parts = course_name.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return course_name  # fallback if no hyphen

# === GET COURSE METADATA ===
def get_course_metadata(course_id, term_cache):
    url = f"{API_BASE_URL}/courses/{course_id}"
    params = {"include[]": ["term"]}
    response = requests.get(url, headers=HEADERS, params=params, timeout=10)
    response.raise_for_status()
    course_data = response.json()

    course_name = course_data.get("name", "Unknown Course")
    coll_course_id = extract_truncated_course_id(course_name)
    sis_course_id = course_data.get("sis_course_id")
    course_name = course_data.get("name", "Unknown Course")
    start_date = course_data.get("start_at", "")
    end_date = course_data.get("end_at", "")
    term_info = course_data.get("term", {})
    term_id = term_info.get("id")
    sis_term_id = term_info.get("sis_term_id", "")

    print(f"[DEBUG1] Course {course_id} | Raw term info: {term_info}")

    if term_id:
        if term_id in term_cache:
            term_name = term_cache[term_id]
        else:
            term_name = term_info.get("name", "Unknown Term")
            term_cache[term_id] = term_name
    else:
        term_name = term_info.get("name", "Unknown Term")

    return start_date, end_date, coll_course_id, course_name, term_name, term_id, sis_term_id, sis_course_id

# === GET SECTION METADATA ===
def get_section_names(course_id, course_term_id=None):
    section_map = {}
    url = f"{API_BASE_URL}/courses/{course_id}/sections"
    params = {"per_page": 100}

    while url:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        sections = response.json()
        print(f"[DEBUG2] Course {course_id} | Total sections fetched: {len(sections)}")

        for s in sections:
            name = s.get("name", "")
            section_term_id = s.get("sis_term_id", "")

            print(f"[DEBUG3] Course {course_id}, {coll_course_id}| Section name: '{name}' | SIS Term ID: '{s.get('sis_term_id')}'")

            # If section has no term ID, fall back to course term
            effective_term_id = s.get("sis_term_id") or course_term_id

            print(f"[DEBUG4] Section '{name}' | Effective Term ID: '{effective_term_id}'")

            if effective_term_id in ["2024/FA", "2024/PF"]:
                print(f"[FILTER] Course {course_id} | Section: '{name}' | Term Match: True")
                section_map[s["sis_section_id"]] = name
            else:
                print(f"[FILTER] Course {course_id} | Section: '{name}' | Term Match: False")

        url = response.links.get("next", {}).get("url")
        params = None

    return section_map

# === GET ENROLLMENTS ===
def get_enrollments(course_id):
    enrollments = []
    url = f"{API_BASE_URL}/courses/{course_id}/enrollments"
    params = {
        "per_page": 100,
        }
    
    while url:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        enrollments.extend(response.json())
        url = response.links.get("next", {}).get("url")
    
    return enrollments

# This function was deemed unnecessary -- keeping it for posterity.
# === TOTAL COURSE MINUTES ===
# def get_student_minutes(course_id):
    student_minutes = {}
    url = f"{API_BASE_URL}/courses/{course_id}/enrollments?type[]=StudentEnrollment&per_page=100"

    while url:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        enrollments = response.json()

        for e in enrollments:
            user = e.get("user", {})
            user_id = user.get("id")
            sis_user_id = user.get("sis_user_id") or user_id
            if not user_id:
                continue

            analytics_url = f"{API_BASE_URL}/courses/{course_id}/analytics/users/{user_id}/activity"
            analytics_resp = requests.get(analytics_url, headers=HEADERS)

            if analytics_resp.status_code == 400:
                print(f"[INFO] No analytics available for user {user_id}")
                student_minutes[sis_user_id] = 0
                continue

            if analytics_resp.status_code == 200:
                data = analytics_resp.json()
                page_views_by_hour = data.get("page_views", {})
                session_count = len(page_views_by_hour)
                total_views = sum(page_views_by_hour.values())

                estimated_minutes = total_views * 0.5

                print(f"[DEBUG5] User {user_id} | Sessions: {session_count} | Views: {total_views} → Estimated: {estimated_minutes} minutes")

                student_minutes[sis_user_id] = estimated_minutes
                
        url = response.links.get("next", {}).get("url")

    return student_minutes

# === GET LAST COURSE ACCESS ===
from dateutil.parser import parse

def get_last_course_access(course_id, user_id):
    url = f"{API_BASE_URL}/courses/{course_id}/analytics/users/{user_id}/activity"
    response = requests.get(url, headers=HEADERS, timeout=10)
    print(f"[DEBUG5] API Response for user {user_id}: {response}")
    if response.status_code == 200:
        data = response.json()
        page_views = data.get("page_views", {})
        if page_views:
            latest_timestamp = max(page_views.keys())
            formatted_date = parse(latest_timestamp).strftime("%Y-%m-%d %H:%M")
            print(f"[DEBUG6] Last access for user {user_id}: {formatted_date}")
            return formatted_date
    return None


# === TRANSFORM DATA ===
def transform_data(enrollments, coll_course_id, course_id, start_date, end_date, course_name, section_map): # Add student_minutes here
    transformed = []
    for e in enrollments:
        section_id = e.get("sis_section_id")
        if section_id not in section_map:
            continue

        user = e.get("user", {})
        user_id = user.get("id")
        last_access = get_last_course_access(course_id, user_id)
        print(f"[DEBUG6] Fetching last access for user {user_id} in course {course_id}")

        transformed.append({
            "enrollmentId": e.get("id"),
            "studentId": user_id,
            "courseId": coll_course_id,
            "courseName": course_name,
            "sectionId": section_id,
            "sectionName": section_map.get(section_id, "Unknown"),
            "startDate": start_date,
            "endDate": end_date,
            "enrollmentStatusCode": e.get("enrollment_state"),
            "enrollmentStatusDesc": "Active enrollment" if e.get("enrollment_state") == "active" else "Inactive enrollment",
            "lastCourseAccess": last_access
        })
    return transformed

# === WRITE TO CSV ===
def write_csv(data):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"canvas_enrollment_data_{timestamp}.csv"
    headers = [
        "enrollmentId",
        "studentId",
        "courseId",
        "courseName",
        "sectionId",
        "sectionName",
        "startDate",
        "endDate",
        "enrollmentStatusCode",
        "enrollmentStatusDesc",
        "lastCourseAccess"

        #"timeSpentInClass" - Add this for student_minutes
    ]
    with open(filename, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        for row in data:
            writer.writerow(row)

# === MAIN EXECUTION ===
if __name__ == "__main__":
    start_time = time.time()
    all_data = []

    print(f"[INFO] Total courses fetched: {len(COURSE_IDS)}")

    TARGET_TERM = "2024 Fall"
    skipped_courses = []

    for course_id in COURSE_IDS:
        print(f"[START] Processing course {course_id}...")

        start_date, end_date, coll_course_id, course_name, term_name, term_id, sis_term_id, sis_course_id = get_course_metadata(course_id, term_cache)

        if term_name != TARGET_TERM:
            reason = f"Wrong term: '{term_name}'"
            skipped_courses.append((course_id, course_name, reason))
            print(f"[SKIP] Course {course_id} ('{course_name}') | Reason: {reason}")
            continue

        section_map = get_section_names(course_id, course_term_id=sis_term_id)

        if not section_map:
            reason = "No matching sections"
            skipped_courses.append((course_id, course_name, reason))
            print(f"[SKIP] No matching sections for course {course_id} ({course_name})")
            continue

        print(f"[MATCH] Course: {course_name} ({course_id}) | Term: {term_name}")
        #print(f"[CALL] Calling get_student_minutes for course {course_id}")
        #student_minutes = get_student_minutes(course_id)

        for sid, sname in section_map.items():
            print(f"         Section: {sname} (ID: {sid})")

        enrollments = get_enrollments(course_id)
        transformed = transform_data(enrollments, coll_course_id, sis_course_id, start_date, end_date, course_name, section_map) # Add student_minutes here
        all_data.extend(transformed)

    # Write once after all courses are processed
    if not DRY_RUN:
        write_csv(all_data)
        print("CSV file created successfully with filtered enrollment data.")

    print(f"\n[DONE] Finished in {time.time() - start_time:.2f} seconds")
    print(f"\n[SUMMARY] Skipped Courses:")
    for course_id, course_name, reason in skipped_courses:
        print(f" - {course_name} (ID: {course_id}, {coll_course_id}) | Reason: {reason}")

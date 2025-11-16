# accounts/views.py
from __future__ import annotations
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.text import slugify
import requests
from requests.utils import parse_header_links
from requests.exceptions import HTTPError, RequestException
from django.shortcuts import render
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from .utils.sdsu_scraper import fetch_html, parse_services, DEFAULT_URL

CANVAS_BASE_URL = "https://sdsu.instructure.com" 
CACHE_KEY = "sdsu_services_list_v1"
CACHE_TTL_SECONDS = 60 * 60 * 12  # 12 hours

def _parse_next_link(resp):
    link_header = resp.headers.get("Link")
    if not link_header:
        return None
    links = parse_header_links(link_header.replace(">,<", ">, <"))
    for l in links:
        if l.get("rel") == "next":
            return l.get("url")
    return None

def _fetch_canvas_courses(token, base_url=CANVAS_BASE_URL, timeout=10):
    """
    Calls Canvas and returns a list of course JSON objects for the token holder.
    Handles pagination via Link headers.
    Raises HTTPError for 4xx/5xx.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = f"{base_url}/api/v1/courses?enrollment_state=active&per_page=100"

    courses = []
    while url:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 401:
            raise HTTPError("Unauthorized (401): invalid or expired Canvas token.", response=resp)
        if resp.status_code == 403:
            raise HTTPError("Forbidden (403): token lacks required permissions.", response=resp)
        resp.raise_for_status()

        page = resp.json()
        if not isinstance(page, list):
            raise ValueError("Unexpected Canvas response shape (expected a list).")
        courses.extend(page)

        url = _parse_next_link(resp)

    return courses

def _extract_subject_names(payload):
    """
    Your rule: course_names = [I['course_code'] for I in payload]
    Be defensive and fall back to 'name' if course_code is missing.
    """
    names = []
    for item in payload:
        name = (item.get("name") or item.get("name") or "").strip()
        if name:
            names.append(name)
    return names
# In-memory "database" — resets on server restart
USERS = {}  # { username: {"password": "...", "full_name": "..."} }
USER_STATE = {}  # { username: {"subjects": ["Math 101", ...], "quiz": {"score": X, "level": "..."} } }

def front_page(request):
    # If already "logged in", go straight to dashboard
    if request.session.get('user'):
        return redirect('dashboard')
    return render(request, 'front_page.html')

def signup(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        password = request.POST.get('password', '')
        full_name = request.POST.get('full_name', '').strip()

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return redirect('front_page')

        if username in USERS:
            messages.error(request, "That username is taken.")
            return redirect('front_page')

        USERS[username] = {"password": password, "full_name": full_name or username}
        messages.success(request, "Signup successful! Please log in.")
        return redirect('front_page')

    return redirect('front_page')

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        password = request.POST.get('password', '')

        user = USERS.get(username)
        if user and user['password'] == password:
            request.session['user'] = username  # mark session as logged in
            return redirect('dashboard')

        messages.error(request, "Invalid credentials.")
        return redirect('front_page')

    return redirect('front_page')

def dashboard(request):
    username = request.session.get('user')
    if not username:
        return redirect('front_page')

    full_name = USERS.get(username, {}).get('full_name', username)
    state = USER_STATE.setdefault(username, {"subjects": [], "quiz": None})
    return render(request, 'dashboard.html', {
        'full_name': full_name,
        'username': username,
        'subjects': state['subjects'],
        'quiz': state['quiz'],
    })


def logout_view(request):
    request.session.flush()
    messages.success(request, "You have been logged out.")
    return redirect('front_page')

# -------------------- QUIZ --------------------

# Simple demo quiz (indirect stress probes)
QUIZ_QUESTIONS = [
    {
        "id": "sleep",
        "text": "How has your sleep felt this week?",
        "choices": [
            ("Great, restful", 0),
            ("Okay, but inconsistent", 1),
            ("Not great, hard to fall/stay asleep", 2),
        ],
    },
    {
        "id": "overwhelm",
        "text": "When deadlines stack up, you feel…",
        "choices": [
            ("Focused, I have a plan", 0),
            ("A bit tense but managing", 1),
            ("Overwhelmed and stuck", 2),
        ],
    },
    {
        "id": "energy",
        "text": "Your daytime energy levels are…",
        "choices": [
            ("High! I'm cruising", 0),
            ("Up and down", 1),
            ("Low and foggy", 2),
        ],
    },
    {
        "id": "support",
        "text": "How supported do you feel by friends/family/campus?",
        "choices": [
            ("Very supported", 0),
            ("Somewhat supported", 1),
            ("Not really supported", 2),
        ],
    },
]

def quiz(request):
    username = request.session.get('user')
    if not username:
        return redirect('front_page')

    if request.method == 'POST':
        # score answers
        score = 0
        for q in QUIZ_QUESTIONS:
            try:
                score += int(request.POST.get(q['id'], 0))
            except (TypeError, ValueError):
                pass

        # classify simple levels
        if score <= 2:
            level = "Low stress"
            color = "good"
        elif score <= 5:
            level = "Moderate stress"
            color = "ok"
        else:
            level = "High stress"
            color = "warn"

        USER_STATE.setdefault(username, {"subjects": [], "quiz": None})
        USER_STATE[username]["quiz"] = {"score": score, "level": level, "color": color}
        return redirect('quiz_result')

    # GET: show quiz page
    return render(request, 'quiz.html', {"questions": QUIZ_QUESTIONS})

def quiz_result(request):
    username = request.session.get('user')
    if not username:
        return redirect('front_page')

    data = USER_STATE.get(username, {}).get("quiz")
    if not data:
        return redirect('quiz')

    # Demo “insights” copy
    insights = {
        "Low stress": [
            "Keep your routines that work (sleep, hydration, movement).",
            "Try a 5-minute gratitude or breathing practice to maintain balance."
        ],
        "Moderate stress": [
            "Try the 4-7-8 breathing pattern or a short mindful walk.",
            "Break tasks into tiny steps; use a 25-min focus timer + 5-min break."
        ],
        "High stress": [
            "Start small: 2 minutes of slow breathing or a gentle stretch.",
            "Consider reaching out to SDSU Counseling & Psychological Services."
        ],
    }
    tips = insights.get(data["level"], [])
    return render(request, 'quiz_result.html', {"quiz": data, "tips": tips})

# -------------------- STUDY --------------------

# Demo mentors & links per subject (hard-coded)
SUBJECT_RESOURCES = {
    "Calculus I": {
        "mentors": ["Jordan A. (Calc/Physics) 12:00-2:00PM", "Sam K. (STEM Center)", "Priya R. (Peer Tutor)"],
        "links": [
            ("Paul’s Online Math Notes (Derivatives)", "https://tutorial.math.lamar.edu/"),
            ("Khan Academy: Calculus I", "https://www.khanacademy.org/math/calculus-1")
        ],
    },
    "Intro to Psychology": {
        "mentors": ["Alexis M. (Psych TA) 3:00-5:00PM", "Wellness Peer Educators"],
        "links": [
            ("SimplyPsych: Memory basics", "https://www.simplypsychology.org/memory.html"),
            ("CrashCourse Psychology", "https://www.youtube.com/playlist?list=PL8dPuuaLjXtOPRKzVLY0jJY-uHOH9KVU6")
        ],
    },
    "CS 150 – Intro to Programming": {
        "mentors": ["Diego F. (CS Tutor) 10:00-11:30AM", "Coding Lab Hours"],
        "links": [
            ("W3Schools Python", "https://www.w3schools.com/python/"),
            ("LeetCode (Easy Warmups)", "https://leetcode.com/problemset/?difficulty=EASY")
        ],
    },
     "CS577-09:Principles and Techniques of Data Science": {
        "mentors": ["Maya T. (Data Science TA) 4:00-5:00PM Tue/Thu", "Ethan L. (Data Science Mentor) 12:30-2:00PM Mon/Wed/Fri"],
        "links": [
            ("Kaggle: Intro to Machine Learning", "https://www.kaggle.com/learn/intro-to-machine-learning"),
            ("Pandas Documentation", "https://pandas.pydata.org/docs/"),
            ("Scikit-learn User Guide", "https://scikit-learn.org/stable/user_guide.html"),
            ("DataCamp: Data Science for Beginners", "https://www.datacamp.com/"),
        ],
    },
}

def study_home(request):
    username = request.session.get('user')
    if not username:
        return redirect('front_page')

    state = USER_STATE.setdefault(username, {"subjects": [], "quiz": None})
    return render(request, 'study_home.html', {"subjects": state["subjects"]})

def study_add_subject(request):
    username = request.session.get('user')
    if not username:
        return redirect('front_page')

    state = USER_STATE.setdefault(username, {"subjects": [], "quiz": None})

    if request.method == 'POST':
        # Option A: real Canvas import using provided token
        token = request.POST.get('token', '').strip()
        if token:
            try:
                payload = _fetch_canvas_courses(token)
                subjects = _extract_subject_names(payload)

                if not subjects:
                    messages.info(request, "No courses found on Canvas for this account.")
                    return redirect('study_home')

                # merge unique while preserving your existing list order
                existing = set(state.get("subjects", []))
                added = False
                for s in subjects:
                    if s not in existing:
                        state["subjects"].append(s)
                        existing.add(s)
                        added = True

                if added:
                    messages.success(request, "Subjects imported from Canvas.")
                else:
                    messages.info(request, "All Canvas subjects were already in your list.")
                return redirect('study_home')

            except HTTPError as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                messages.error(request, f"Canvas API error ({status}): {e}")
                return redirect('study_home')
            except RequestException as e:
                messages.error(request, f"Network error calling Canvas: {e}")
                return redirect('study_home')
            except ValueError as e:
                messages.error(request, f"Unexpected Canvas response: {e}")
                return redirect('study_home')

        # Option B: add manual subject
        manual = request.POST.get('manual_subject', '').strip()
        if manual:
            if manual not in state["subjects"]:
                state["subjects"].append(manual)
            messages.success(request, f"Added subject: {manual}")
            return redirect('study_home')

        messages.error(request, "Enter a token to import or a subject name to add.")
        return redirect('study_home')

    return redirect('study_home')


def study_subject(request, subject):
    username = request.session.get('user')
    if not username:
        return redirect('front_page')

    # subject in URL is slug; try to match against user's list
    state = USER_STATE.setdefault(username, {"subjects": [], "quiz": None})
    # Find the display name from user list by slug
    display = None
    for s in state["subjects"]:
        if slugify(s) == subject:
            display = s
            break

    if display is None:
        messages.error(request, "Subject not found.")
        return redirect('study_home')

    resources = SUBJECT_RESOURCES.get(display, {
        "mentors": ["Campus Tutoring Center", "Peer Mentors"],
        "links": [("SDSU Library", "https://library.sdsu.edu/")],
    })
    return render(request, 'study_subject.html', {"subject": display, "resources": resources, "slugify": slugify})


def _get_all_services() -> list[dict]:
    """Fetch + parse + cache the full list."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    html = fetch_html(DEFAULT_URL)
    pairs = parse_services(html, DEFAULT_URL)  # [(name, url), ...]
    items = [{"name": n, "url": u} for n, u in pairs]

    cache.set(CACHE_KEY, items, CACHE_TTL_SECONDS)
    return items

def programs_list(request: HttpRequest) -> HttpResponse:
    page = request.GET.get("page", "1")
    page_size = request.GET.get("page_size", "20")

    try:
        page_size_int = max(1, min(100, int(page_size)))
    except ValueError:
        page_size_int = 20

    items = _get_all_services()

    paginator = Paginator(items, page_size_int)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "total_items": paginator.count,
        "page_size": page_size_int,
        "title": "All SDSU Programs",
    }
    return render(request, "programs_list.html", context)
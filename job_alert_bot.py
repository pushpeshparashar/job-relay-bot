"""
Relay Job Alert Bot — Pushpesh Edition
----------------------------------------
Hardcoded for:
  - SDE / Software Developer roles only
  - India locations (Bengaluru, Hyderabad, Pune, Mumbai, Delhi, Noida,
    Gurgaon, Chennai, Remote-India) + worldwide remote
  - Fresher-friendly (no senior/lead/manager titles, no 3+ years required)
  - Skills from resume: Java, JavaScript, SQL, MySQL, PostgreSQL,
    REST APIs, .NET Core, ASP.NET, JDBC, Git, OOP, DSA

All config can be overridden via GitHub Actions Secrets.
"""

import os
import re
import json
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

STATE_FILE = "state.json"

# ── helpers ──────────────────────────────────────────────────────────────────

def get_env_list(name, default=""):
    raw = os.environ.get(name, default)
    return [s.strip().lower() for s in raw.split(",") if s.strip()]

def get_env_bool(name, default=True):
    raw = os.environ.get(name, "").strip().lower()
    return default if raw == "" else raw in ("1", "true", "yes", "on")

# ── config (resume-baked defaults, overridable via secrets) ──────────────────

SKILLS = get_env_list("SKILLS",
    "java, javascript, python, html, css, sql, mysql, postgresql, "
    "rest api, jdbc, git, oop, data structures, dsa, .net core, asp.net, "
    "problem solving, agile"
)

MUST_HAVES = get_env_list("MUST_HAVES", "")   # keep empty = don't over-restrict
THRESHOLD  = int(os.environ.get("THRESHOLD", "20"))

# SDE role keywords — job title must contain at least one of these
SDE_ROLE_KEYWORDS = get_env_list("SDE_ROLE_KEYWORDS",
    "software engineer, software developer, sde, backend developer, "
    "backend engineer, full stack, fullstack, full-stack, java developer, "
    "web developer, application developer, trainee developer, "
    "junior developer, junior engineer, associate engineer, "
    "associate developer, graduate engineer, software trainee, "
    "fresher developer, entry level developer, programmer"
)

# India city / region keywords
INDIA_LOCATIONS = [
    "india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai",
    "delhi", "new delhi", "noida", "gurgaon", "gurugram", "chennai",
    "kolkata", "ahmedabad", "jaipur", "remote"   # remote is global so allowed
]

FRESHER_MODE      = get_env_bool("FRESHER_MODE", default=True)
EXCLUDE_KEYWORDS  = get_env_list("EXCLUDE_KEYWORDS",
    "php, wordpress, devops, embedded, hardware, ios, android, "
    "react native, flutter, data scientist, ml engineer, blockchain"
)

SENIOR_TERMS = [
    "senior", "sr.", " sr ", "lead ", "principal", "staff engineer",
    "architect", "manager", "director", "head of", " vp ", "vice president",
    "tech lead", "team lead",
]
YEARS_PATTERN = re.compile(r"(\d+)\s*\+?\s*(?:to\s*\d+\s*)?years?")

SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EMAIL_TO  = os.environ["EMAIL_TO"]

# ── fetchers ─────────────────────────────────────────────────────────────────

def fetch_remoteok():
    try:
        r = requests.get(
            "https://remoteok.com/api", timeout=20,
            headers={"User-Agent": "relay-job-alert-bot (personal use)"},
        )
        r.raise_for_status()
        jobs = []
        for d in r.json():
            if not d.get("id"):
                continue
            jobs.append({
                "id":       f"remoteok-{d['id']}",
                "title":    d.get("position", ""),
                "company":  d.get("company", ""),
                "location": d.get("location") or "Remote",
                "source":   "RemoteOK",
                "url":      f"https://remoteok.com{d['url']}" if d.get("url") else "",
                "tags":     d.get("tags") or [],
            })
        return jobs
    except Exception as e:
        print(f"RemoteOK fetch failed: {e}")
        return []


def fetch_arbeitnow():
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=20)
        r.raise_for_status()
        jobs = []
        for d in r.json().get("data", []):
            jobs.append({
                "id":       f"arbeitnow-{d.get('slug')}",
                "title":    d.get("title", ""),
                "company":  d.get("company_name", ""),
                "location": "Remote" if d.get("remote") else (d.get("location") or "Unspecified"),
                "source":   "Arbeitnow",
                "url":      d.get("url", ""),
                "tags":     d.get("tags") or [],
            })
        return jobs
    except Exception as e:
        print(f"Arbeitnow fetch failed: {e}")
        return []


def fetch_jobicy():
    try:
        params = {"count": 50, "tag": "java"}   # seed with java to bias results
        r = requests.get("https://jobicy.com/api/v2/remote-jobs", params=params, timeout=20)
        r.raise_for_status()
        jobs = []
        for d in r.json().get("jobs", []):
            jobs.append({
                "id":       f"jobicy-{d.get('id')}",
                "title":    d.get("jobTitle", ""),
                "company":  d.get("companyName", ""),
                "location": d.get("jobGeo") or "Remote",
                "source":   "Jobicy",
                "url":      d.get("url", ""),
                "tags":     d.get("jobIndustry") or [],
            })
        return jobs
    except Exception as e:
        print(f"Jobicy fetch failed: {e}")
        return []

# ── filters ──────────────────────────────────────────────────────────────────

def is_india_or_remote(job):
    """Accept only India-based or fully remote (worldwide) roles."""
    loc = job["location"].lower()
    return any(city in loc for city in INDIA_LOCATIONS)


def is_sde_role(job):
    """Job title must contain at least one SDE-family keyword."""
    title = job["title"].lower()
    return any(kw in title for kw in SDE_ROLE_KEYWORDS)


def matches_filters(job):
    hay = f"{job['title']} {job['company']} {job['location']} {' '.join(job.get('tags', []))}".lower()

    # 1. India or remote only
    if not is_india_or_remote(job):
        return False

    # 2. Must be an SDE-type role
    if not is_sde_role(job):
        return False

    # 3. Blocked keywords (irrelevant stacks)
    if EXCLUDE_KEYWORDS and any(term in hay for term in EXCLUDE_KEYWORDS):
        return False

    # 4. Fresher mode — no senior titles, no 3+ years requirement
    if FRESHER_MODE:
        if any(term in hay for term in SENIOR_TERMS):
            return False
        years_found = [int(m) for m in YEARS_PATTERN.findall(hay)]
        if any(y >= 3 for y in years_found):
            return False

    return True

# ── scoring ──────────────────────────────────────────────────────────────────

def score_job(job):
    hay = f"{job['title']} {job['company']} {job['location']} {' '.join(job.get('tags', []))}".lower()
    base = 50
    if SKILLS:
        hits = sum(1 for s in SKILLS if s in hay)
        base = round((hits / len(SKILLS)) * 100)
    if MUST_HAVES:
        must_hits = sum(1 for s in MUST_HAVES if s in hay)
        ratio = must_hits / len(MUST_HAVES)
        base = round(base * (0.3 + 0.7 * ratio))

    # Bonus: India-city match scores higher than generic "Remote"
    loc = job["location"].lower()
    india_cities = ["bengaluru", "bangalore", "hyderabad", "pune", "mumbai",
                    "delhi", "noida", "gurgaon", "gurugram", "chennai"]
    if any(c in loc for c in india_cities):
        base = min(100, base + 10)

    return max(0, min(100, base))

# ── state ─────────────────────────────────────────────────────────────────────

def load_seen_ids():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen_ids(seen_ids):
    with open(STATE_FILE, "w") as f:
        json.dump(list(seen_ids)[-3000:], f)

# ── email ─────────────────────────────────────────────────────────────────────

def build_email(matches):
    subject = f"Relay SDE Alert: {len(matches)} new India job{'s' if len(matches) != 1 else ''}"

    html_rows = ""
    text_lines = []
    for j in matches:
        score_color = "#27ae60" if j["score"] >= 50 else "#e67e22" if j["score"] >= 30 else "#e74c3c"
        html_rows += (
            f"<tr>"
            f"<td style='padding:10px;border-bottom:1px solid #eee'>"
            f"  <b>{j['title']}</b><br>"
            f"  <span style='color:#555'>{j['company']} &mdash; {j['location']}</span><br>"
            f"  <span style='font-size:12px;color:#888'>{j['source']}</span>"
            f"</td>"
            f"<td style='padding:10px;border-bottom:1px solid #eee;text-align:center'>"
            f"  <span style='color:{score_color};font-weight:bold;font-size:16px'>{j['score']}%</span>"
            f"</td>"
            f"<td style='padding:10px;border-bottom:1px solid #eee;text-align:center'>"
            f"  <a href='{j['url']}' style='background:#2c3e50;color:#fff;padding:6px 14px;"
            f"     border-radius:4px;text-decoration:none;font-size:13px'>Apply</a>"
            f"</td>"
            f"</tr>"
        )
        text_lines.append(f"[{j['score']}%] {j['title']} @ {j['company']} ({j['location']}) -> {j['url']}")

    html_body = f"""
    <div style='font-family:sans-serif;max-width:640px;margin:auto'>
      <h2 style='background:#2c3e50;color:#fff;padding:16px;border-radius:6px 6px 0 0;margin:0'>
        🔍 Relay SDE Job Alert
      </h2>
      <p style='padding:12px;background:#f9f9f9;margin:0;color:#555'>
        {len(matches)} new SDE role{'s' if len(matches) != 1 else ''} found in India matching your profile.
        Sorted by match score.
      </p>
      <table style='width:100%;border-collapse:collapse'>
        <tr style='background:#ecf0f1'>
          <th style='padding:10px;text-align:left'>Role</th>
          <th style='padding:10px'>Match</th>
          <th style='padding:10px'>Link</th>
        </tr>
        {html_rows}
      </table>
      <p style='padding:12px;color:#aaa;font-size:12px'>
        Relay Job Bot — runs twice daily. Reply to this email to unsubscribe.
      </p>
    </div>
    """
    text_body = "New SDE jobs in India:\n\n" + "\n".join(text_lines)
    return subject, text_body, html_body


def send_email(subject, text_body, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    all_jobs = fetch_remoteok() + fetch_arbeitnow() + fetch_jobicy()
    filtered = [j for j in all_jobs if matches_filters(j)]
    for j in filtered:
        j["score"] = score_job(j)

    seen = load_seen_ids()
    new_matches = [j for j in filtered if j["id"] not in seen and j["score"] >= THRESHOLD]
    new_matches.sort(key=lambda j: j["score"], reverse=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"{ts} | total fetched: {len(all_jobs)} | after India+SDE filter: {len(filtered)} | new matches: {len(new_matches)}")

    if new_matches:
        subject, text_body, html_body = build_email(new_matches)
        send_email(subject, text_body, html_body)
        print(f"Email sent — {len(new_matches)} jobs.")
        for j in new_matches:
            print(f"  {j['score']}% | {j['title']} @ {j['company']} ({j['location']})")
    else:
        print("No new matches — no email sent.")

    seen.update(j["id"] for j in filtered)
    save_seen_ids(seen)


if __name__ == "__main__":
    main()

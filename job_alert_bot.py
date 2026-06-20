"""
Relay Job Alert Bot
--------------------
Checks public job-board APIs (RemoteOK, Arbeitnow, Jobicy), scores results
against your skills/must-haves, and emails you only the NEW matches above
your threshold. Designed to run on a schedule via GitHub Actions.

No login, no scraping of sites that forbid it, no forms submitted anywhere
-> nothing here will ever trigger a CAPTCHA.
"""

import os
import json
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

STATE_FILE = "state.json"


def get_env_list(name):
    raw = os.environ.get(name, "")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


SKILLS = get_env_list("SKILLS")
MUST_HAVES = get_env_list("MUST_HAVES")
THRESHOLD = int(os.environ.get("THRESHOLD", "30"))
KEYWORD = os.environ.get("KEYWORD", "").strip()
LOCATION = os.environ.get("LOCATION", "").strip()

SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EMAIL_TO = os.environ["EMAIL_TO"]


def fetch_remoteok():
    try:
        r = requests.get(
            "https://remoteok.com/api",
            timeout=20,
            headers={"User-Agent": "relay-job-alert-bot (personal use)"},
        )
        r.raise_for_status()
        data = r.json()
        jobs = []
        for d in data:
            if not d.get("id"):
                continue
            jobs.append({
                "id": f"remoteok-{d['id']}",
                "title": d.get("position", ""),
                "company": d.get("company", ""),
                "location": d.get("location") or "Remote",
                "source": "RemoteOK",
                "url": f"https://remoteok.com{d.get('url', '')}" if d.get("url") else "",
                "tags": d.get("tags") or [],
            })
        return jobs
    except Exception as e:
        print(f"RemoteOK fetch failed: {e}")
        return []


def fetch_arbeitnow():
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=20)
        r.raise_for_status()
        data = r.json()
        jobs = []
        for d in data.get("data", []):
            jobs.append({
                "id": f"arbeitnow-{d.get('slug')}",
                "title": d.get("title", ""),
                "company": d.get("company_name", ""),
                "location": "Remote" if d.get("remote") else (d.get("location") or "Unspecified"),
                "source": "Arbeitnow",
                "url": d.get("url", ""),
                "tags": d.get("tags") or [],
            })
        return jobs
    except Exception as e:
        print(f"Arbeitnow fetch failed: {e}")
        return []


def fetch_jobicy():
    try:
        params = {"count": 50}
        if KEYWORD:
            params["tag"] = KEYWORD
        r = requests.get("https://jobicy.com/api/v2/remote-jobs", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        jobs = []
        for d in data.get("jobs", []):
            jobs.append({
                "id": f"jobicy-{d.get('id')}",
                "title": d.get("jobTitle", ""),
                "company": d.get("companyName", ""),
                "location": d.get("jobGeo") or "Remote",
                "source": "Jobicy",
                "url": d.get("url", ""),
                "tags": d.get("jobIndustry") or [],
            })
        return jobs
    except Exception as e:
        print(f"Jobicy fetch failed: {e}")
        return []


def matches_filters(job):
    hay = f"{job['title']} {job['company']} {job['location']}".lower()
    if KEYWORD and KEYWORD.lower() not in hay:
        return False
    if LOCATION:
        loc = job["location"].lower()
        if LOCATION.lower() not in loc and "remote" not in loc:
            return False
    return True


def score_job(job):
    hay = f"{job['title']} {job['company']} {job['location']} {' '.join(job.get('tags', []))}".lower()
    base = 50  # neutral if no criteria configured
    if SKILLS:
        hits = sum(1 for s in SKILLS if s in hay)
        base = round((hits / len(SKILLS)) * 100)
    if MUST_HAVES:
        must_hits = sum(1 for s in MUST_HAVES if s in hay)
        ratio = must_hits / len(MUST_HAVES)
        base = round(base * (0.3 + 0.7 * ratio))  # heavy penalty if must-haves missing
    return max(0, min(100, base))


def load_seen_ids():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen_ids(seen_ids):
    trimmed = list(seen_ids)[-3000:]  # keep file small
    with open(STATE_FILE, "w") as f:
        json.dump(trimmed, f)


def build_email(matches):
    subject = f"Relay: {len(matches)} new job match{'es' if len(matches) != 1 else ''}"
    text_lines, html_lines = [], []
    for j in matches:
        text_lines.append(f"- [{j['score']}%] {j['title']} @ {j['company']} ({j['location']}) -> {j['url']}")
        html_lines.append(
            f"<li><b>{j['score']}%</b> &mdash; <b>{j['title']}</b> at {j['company']} "
            f"<span style='color:#888'>({j['location']}, {j['source']})</span><br>"
            f"<a href='{j['url']}'>Open &amp; apply</a></li>"
        )
    text_body = "New job matches:\n\n" + "\n".join(text_lines)
    html_body = "<h3>New job matches</h3><ul>" + "".join(html_lines) + "</ul>"
    return subject, text_body, html_body


def send_email(subject, text_body, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())


def main():
    all_jobs = fetch_remoteok() + fetch_arbeitnow() + fetch_jobicy()
    all_jobs = [j for j in all_jobs if matches_filters(j)]
    for j in all_jobs:
        j["score"] = score_job(j)

    seen = load_seen_ids()
    new_matches = [j for j in all_jobs if j["id"] not in seen and j["score"] >= THRESHOLD]
    new_matches.sort(key=lambda j: j["score"], reverse=True)

    ts = datetime.now(timezone.utc).isoformat()
    print(f"{ts} - fetched {len(all_jobs)} jobs total, {len(new_matches)} new matches >= {THRESHOLD}%")

    if new_matches:
        subject, text_body, html_body = build_email(new_matches)
        send_email(subject, text_body, html_body)
        print(f"Email sent with {len(new_matches)} matches.")
    else:
        print("No new matches above threshold - no email sent.")

    seen.update(j["id"] for j in all_jobs)
    save_seen_ids(seen)


if __name__ == "__main__":
    main()

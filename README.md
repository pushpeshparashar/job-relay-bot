# Relay Job Alert Bot

Checks RemoteOK, Arbeitnow, and Jobicy twice a day, scores every job against
your skills, and emails you only the **new** matches above your threshold.
No login anywhere, no scraping of sites that disallow it, no forms submitted
— so there's nothing here that will ever hit a CAPTCHA.

## 1. Create the repo

1. Go to github.com → New repository → name it e.g. `relay-job-bot` →
   keep it **Private** (recommended, since secrets live alongside it) → Create.
2. Upload these files keeping the folder structure exactly:
   ```
   job_alert_bot.py
   requirements.txt
   state.json
   .github/workflows/job-alert.yml
   ```
   Easiest way: on the repo page, click "Add file" → "Upload files", drag
   all of them in (GitHub will recreate the `.github/workflows/` folder
   automatically from the path).

## 2. Get an email sender (SMTP) you can use from code

Easiest option — a Gmail **App Password** (free, 2 minutes):
1. Turn on 2-Step Verification on the Gmail account you want to send *from*:
   https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password (name it "Relay Bot"), copy the 16-character code.
4. Use:
   - `SMTP_HOST` = `smtp.gmail.com`
   - `SMTP_PORT` = `587`
   - `SMTP_USER` = your Gmail address
   - `SMTP_PASS` = the 16-character app password (not your normal Gmail password)

(Outlook/Yahoo work the same way with their own SMTP host + app password.)

## 3. Add your secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret.**
Add each of these one at a time:

| Secret name   | Example value                  | Notes |
|---------------|----------------------------------|-------|
| `SMTP_HOST`   | `smtp.gmail.com`                | |
| `SMTP_PORT`   | `587`                           | |
| `SMTP_USER`   | `you@gmail.com`                 | the sending account |
| `SMTP_PASS`   | `abcd efgh ijkl mnop`            | the app password |
| `EMAIL_TO`    | `you@gmail.com`                 | where alerts land — can be same as sender |
| `SKILLS`      | `react, node, sql, aws`         | comma-separated, optional |
| `MUST_HAVES`  | `remote`                        | comma-separated, optional — jobs missing these get scored much lower |
| `THRESHOLD`   | `40`                            | only matches at/above this % get emailed |
| `KEYWORD`     | `frontend developer`            | optional, narrows the initial fetch |
| `LOCATION`    | `Bengaluru`                     | optional |

Leave `SKILLS`/`MUST_HAVES`/`KEYWORD`/`LOCATION` blank (or skip them) if you
want the broadest possible sweep.

## 4. Turn it on

1. Go to the **Actions** tab of your repo → you should see "Relay Job Alert Bot".
2. Click into it → **Run workflow** (this is the `workflow_dispatch` trigger) to
   test it immediately instead of waiting for the schedule.
3. Check the run logs — it'll print how many jobs it found and whether it sent
   an email. Check your inbox (and spam folder, the first time).
4. If that works, you're done — it will now run automatically at ~9:00 AM and
   ~6:00 PM IST every day, only emailing you about *new* matches each time.

## Notes & honest limitations

- **Timing**: GitHub's free scheduler can run a few minutes late during busy
  periods — it's "around" 9am/6pm, not to the second.
- **Coverage**: this only covers RemoteOK, Arbeitnow, and Jobicy — the boards
  with public APIs. For LinkedIn, Indeed, Naukri, Glassdoor, turn on their own
  native "job alert" emails (each has one in their search settings) — that's
  the legitimate equivalent for sites that don't allow third-party automation.
- **Memory**: `state.json` is how it remembers what it already emailed you
  about, so you won't get the same job twice. The workflow commits this file
  back to your repo after every run — that's expected, ignore the auto-commits.
- **Tuning scores**: if you're getting 0 matches, lower `THRESHOLD` or loosen
  `MUST_HAVES`. If you're getting too many, tighten them.

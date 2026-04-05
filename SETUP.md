# LinkedIn Bot — One-Time Setup Guide

This runs on GitHub Actions (GitHub's cloud servers). Your computer can be completely off.

---

## Step 1 — Create a Personal Access Token (PAT)

GitHub needs a token to push application logs back to the repo after each run.

1. Go to: https://github.com/settings/tokens/new
2. Note: `linkedin-bot-access`
3. Expiration: `No expiration` (or 1 year)
4. Scopes: check **`repo`** (full repo access)
5. Click **Generate token**
6. **Copy the token immediately** — you won't see it again

---

## Step 2 — Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these 4 secrets:

| Secret Name | Value |
|---|---|
| `LINKEDIN_EMAIL` | libbygonzalodo@gmail.com |
| `LINKEDIN_PASSWORD` | Your LinkedIn password |
| `ANTHROPIC_API_KEY` | Your Claude API key (from console.anthropic.com) |
| `GH_PAT` | The token you just created in Step 1 |

---

## Step 3 — Get Your Claude API Key

1. Go to: https://console.anthropic.com/
2. Click **API Keys** → **Create Key**
3. Name it `linkedin-resume-tailor`
4. Copy the key and add it as `ANTHROPIC_API_KEY` secret above
5. Note: Resume tailoring costs ~$0.01–0.03 per application (Haiku model — cheapest)

---

## Step 4 — Enable GitHub Actions

1. Go to your repo → **Actions** tab
2. If prompted, click **"I understand my workflows, go ahead and enable them"**

---

## Step 5 — Run It Manually First

Before waiting for the scheduled run, test it:

1. Go to **Actions** → **LinkedIn Job Applications**
2. Click **Run workflow** → **Run workflow**
3. Watch the logs in real time
4. Check that it logs in successfully, finds jobs, and submits applications
5. Verify `data/applied_jobs.json` and `data/pipeline.md` are updated in a new commit

---

## Schedule

The bot runs automatically **3 times per weekday** (Mon–Fri):
- 9:00 AM Pacific Time
- 1:00 PM Pacific Time
- 5:00 PM Pacific Time

**Target: 50 applications per run = up to 150/day**

---

## Monitoring

- **Check applied_jobs.json** in your repo — updated after every run
- **Check pipeline.md** — markdown table of all applications
- **Check Actions tab** — full logs for every run
- **Check your LinkedIn** — "Applied jobs" section confirms each submission
- Also synced to: `C:\Users\libby\Claude\projects\active\career-os\pipeline.md` (copy manually or set up sync)

---

## Updating Job Criteria

Edit `data/config.json` to change:
- `job_search.titles` — job titles to search
- `job_search.locations` — search locations
- `job_search.salary_minimum_usd` — minimum salary filter
- `application_limits.max_per_run` — currently 50

---

## Troubleshooting

**Bot gets CAPTCHA or security challenge:**
LinkedIn occasionally requires human verification. If you see this in the logs, log into LinkedIn manually on your phone or computer to clear it, then re-run the workflow.

**"No Easy Apply button found":**
The job is not Easy Apply — the bot correctly skips it.

**"manual_review_required":**
The application form has required fields (salary expectation, complex questions) the bot can't fill safely. These are skipped and logged.

**Workflow not running on schedule:**
GitHub may pause scheduled workflows on repos with no recent activity. Push any small change to reactivate.

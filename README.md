# Nyatsime Independent College — Academic Portal

A full school management system built with Python (stdlib only) + SQLite + vanilla JS.

## Features

- **3 Portals**: Admin, Staff, Learner
- **Marks** — Enter, view, and delete assessment results by term
- **Attendance** — Take class attendance, view records
- **Timetable** — View/manage class schedules with weekly grid
- **Reports** — Generate printable PDF report cards per learner per term
- **Learners** — Full register with registration form
- **Staff** — Staff directory, add new staff
- **Fees** — USD fee billing, payment recording, progress tracking
- **Textbooks** — Library inventory, issue/return tracking
- **Notices** — Post announcements to staff, learners, or everyone

## Demo Credentials

| Role    | Email                        | Password    |
|---------|------------------------------|-------------|
| Admin   | admin@nyatsime.ac.zw         | admin123    |
| Teacher | teacher@nyatsime.ac.zw       | teacher123  |
| Learner | learner@nyatsime.ac.zw       | learner123  |

## Run Locally (Termux / Any machine)

```bash
python app.py
# Open http://localhost:5000
```

No pip installs needed — pure Python standard library.

## Deploy to Railway (Free)

1. Push this folder to a GitHub repo
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Select your repo — Railway auto-detects Python + Procfile
4. Click Deploy → Get your public URL in ~2 minutes

**Note on database:** Railway's free tier uses ephemeral storage — the SQLite DB resets on redeploy. For a permanent school deployment, upgrade to a paid plan ($5/mo) which gives persistent disk, or migrate to PostgreSQL (free on Railway).

## Deploy to Render (Free)

1. Push to GitHub
2. Go to https://render.com → New → Web Service
3. Connect your repo
4. Build Command: (leave blank)
5. Start Command: `python app.py`
6. Deploy

## Accessing from the school network

Run on a computer/phone connected to school Wi-Fi:

```bash
python app.py
# Students connect to http://YOUR_IP:5000
```

Find your IP with: `ip addr show wlan0` (Linux) or `ipconfig` (Windows)

## File Structure

```
nyatsime/
├── app.py          # Python backend + API (stdlib only)
├── index.html      # Full frontend (single-file SPA)
├── school.db       # SQLite database (auto-created on first run)
├── Procfile        # For Railway/Render deployment
├── runtime.txt     # Python version
└── requirements.txt
```

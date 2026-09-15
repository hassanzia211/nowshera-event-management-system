# Nowshera Events — Registration & Management System

A complete Flask + SQLite implementation of the supplied PRD. It supports attendee and admin roles, event capacity, registration/cancellation, attendee search and CSV export, persistent dashboard totals, and responsive screens.

## Run on macOS / Windows

```bash
python -m venv .venv
```

Activate it:

```bash
# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Then install and run:

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Demo accounts

- Admin: `admin@nowshera.test` / `Admin123!`
- Attendee: `attendee@nowshera.test` / `Attend123!`

Create events as admin, publish them using the Dashboard status menu, then sign in as the attendee to register.

## Security and correctness

- Passwords are hashed.
- Admin routes and actions are protected on the server.
- Registration ownership is checked on the server.
- `BEGIN IMMEDIATE` serializes capacity checks and booking writes to prevent overbooking.
- A partial unique database index prevents duplicate active registrations.
- Data is stored in `instance/events.db` and survives refresh/restart.

## Optional n8n automation bonus

Import `n8n/event-notifications-workflow.json` into n8n, connect the three Gmail nodes to your Gmail credential, activate the workflow, and copy its Production Webhook URL. Set that URL before starting Flask:

```powershell
$env:N8N_WEBHOOK_URL="PASTE_PRODUCTION_WEBHOOK_URL_HERE"
python app.py
```

The website then sends registration confirmations, cancellation confirmations, and an admin alert when an event becomes full. If n8n is unavailable, the core website continues to work.

## Submission test checklist

Use the supplied demo accounts plus newly created attendee accounts to perform the 10 PRD tests: successful registration, draft/publish visibility, duplicate booking, full event, closed/past event, cancellation reopening capacity, invalid capacity, admin authorization, registration ownership, and attendee-list/search/export/dashboard persistence.

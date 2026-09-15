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

## Submission test checklist

Use the supplied demo accounts plus newly created attendee accounts to perform the 10 PRD tests: successful registration, draft/publish visibility, duplicate booking, full event, closed/past event, cancellation reopening capacity, invalid capacity, admin authorization, registration ownership, and attendee-list/search/export/dashboard persistence.

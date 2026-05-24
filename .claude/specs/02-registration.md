# Spec: Registration

## Overview
Wire up the registration form so new visitors can create a Spendly account. The
`GET /register` route and `register.html` template are already in place; this step
adds `POST /register` to validate input, hash the password, persist the new user,
start a Flask session, and redirect to the landing page. It also adds the
`create_user()` and `get_user_by_email()` helpers to `database/db.py`, sets
`app.secret_key` so sessions work, and fixes the one hardcoded URL in the form.

## Depends on
- Step 1 — Database setup (`get_db()`, `users` table, `init_db()`)

## Routes
- `POST /register` — validates form data, creates user, starts session, redirects to `/` — public

`GET /register` already exists; its handler does not change.

## Database changes
No new tables or columns. Two new helper functions added to `database/db.py`:

- `get_user_by_email(email)` — returns the `sqlite3.Row` for the given email, or `None`
- `create_user(name, email, password_hash)` — inserts a row into `users`, returns the new `id`

## Templates
- **Create:** none
- **Modify:** `templates/register.html`
  - Change `action="/register"` to `action="{{ url_for('register') }}"` — never hardcode URLs

## Files to change
- `app.py` — add `POST /register` route; set `app.secret_key`; add imports: `request`, `session`, `redirect`
- `database/db.py` — add `get_user_by_email()` and `create_user()`
- `templates/register.html` — fix hardcoded form `action`

## Files to create
None.

## New dependencies
No new pip packages. Uses only:
- `werkzeug.security.generate_password_hash` (already imported in `db.py`)
- `flask.session`, `flask.redirect`, `flask.request` (already in requirements)

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — no f-strings or `%` formatting in SQL
- Passwords hashed with `werkzeug.security.generate_password_hash` before any DB write — never store plaintext
- `app.secret_key` must be set before any `session` usage — use `"dev-secret-change-me"` for now
- All templates extend `base.html`
- Use CSS variables — never hardcode hex values
- All internal links use `url_for()`
- DB logic stays in `database/db.py` — the route function must not execute SQL directly
- On duplicate email: catch `sqlite3.IntegrityError`, re-render `register.html` with `error="An account with that email already exists."`
- Server-side validation in the route (not just browser-side): name non-empty, password at least 8 characters; on failure re-render with a specific `error` message
- On success: set `session['user_id']` and `session['user_name']`, then `redirect(url_for('landing'))`
- Use `abort(400)` only for malformed requests; use `error=` re-render for ordinary validation failures

## Definition of done
- [ ] Submitting the form with a new email creates a row in `users` with a hashed (not plaintext) password
- [ ] After successful registration the browser lands on the landing page (`/`)
- [ ] `session['user_id']` is set after registration (verifiable via Flask shell or browser dev tools → Application → Cookies)
- [ ] Submitting with a duplicate email re-renders the form showing a visible error — no 500 crash
- [ ] Submitting with a password shorter than 8 characters re-renders the form with a visible error
- [ ] Submitting with an empty name re-renders the form with a visible error
- [ ] `register.html` uses `url_for('register')` in the form `action` — no hardcoded path
- [ ] No SQL is written inside `app.py` — all DB calls go through `database/db.py` helpers
- [ ] App starts without errors after changes

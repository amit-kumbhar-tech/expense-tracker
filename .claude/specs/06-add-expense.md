# Spec: Add Expense

## Overview
This step implements the full "add expense" flow: a form where a logged-in user can record a new expense (amount, category, date, optional description) and submit it to be persisted in the `expenses` table. The current route stub returns a plain string; this step replaces it with a real GET/POST handler backed by a new `create_expense` DB helper. On success the user is redirected to their profile page. Access is restricted to logged-in users.

## Depends on
- Step 01 — database setup (`get_db()`, `expenses` table schema)
- Step 02 — registration (user records exist)
- Step 03 — login/logout (session management, `session['user_id']`)
- Step 05 — date filter / profile page (profile is the redirect target after a successful add)

## Routes
- `GET /expenses/add` — render the add-expense form — logged-in only
- `POST /expenses/add` — validate and persist the new expense, then redirect to `/profile` — logged-in only

## Database changes
No schema changes. The `expenses` table already has all required columns:
- `user_id` (INTEGER, FK → users.id)
- `amount` (REAL)
- `category` (TEXT)
- `date` (TEXT, ISO format YYYY-MM-DD)
- `description` (TEXT, nullable)

A new DB helper `create_expense` must be added to `database/db.py`.

## Templates
- **Create:** `templates/add_expense.html`
  - Extends `base.html`
  - Form with fields: amount (number), category (select), date (date input, defaults to today), description (text, optional)
  - Inline validation error display (re-render with error message on bad input)
  - Cancel link back to `/profile` using `url_for`

## Files to change
- `app.py`
  - Update the existing `add_expense` route to accept `GET` and `POST`
  - Guard: redirect to `/login` if `session.get('user_id')` is falsy
  - GET: render `add_expense.html` with today's date pre-filled
  - POST: validate fields, call `create_expense(...)`, redirect to `/profile` on success; re-render with error on failure
  - Import `create_expense` from `database.db`
- `database/db.py`
  - Add `create_expense(user_id, amount, category, date, description)` helper

## Files to create
- `templates/add_expense.html` — the add-expense form template
- `static/css/add_expense.css` — page-specific styles for the form

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — use `sqlite3` via `get_db()` only
- Parameterised queries only — never interpolate variables into SQL strings
- Passwords are never touched in this step
- Use CSS variables — never hardcode hex colour values in CSS
- All templates extend `base.html`
- The route must redirect (302) to `/login` if no session exists — never show a 401
- Amount must be a positive number; reject zero or negative values with an error message
- Category must be one of the allowed values: Food, Transport, Bills, Health, Entertainment, Shopping, Other
- Date must be a valid ISO date (YYYY-MM-DD); default to today if not supplied
- Description is optional — store `None` / empty string if omitted
- On success, redirect to `url_for('profile')` — never re-render the form
- On validation failure, re-render `add_expense.html` with the submitted values pre-filled and an error message

## DB helper to add in `database/db.py`
```python
def create_expense(user_id, amount, category, date, description):
    """Insert a new expense row; return the new row's id."""
```

## Definition of done
- [ ] `GET /expenses/add` while logged out redirects to `/login`
- [ ] `GET /expenses/add` while logged in renders the form with today's date pre-filled
- [ ] Form has fields for amount, category (dropdown), date, and description
- [ ] Submitting a valid expense saves a row to the `expenses` table and redirects to `/profile`
- [ ] The new expense appears in the profile page's transaction list
- [ ] Submitting with an empty amount shows a validation error and does not insert a row
- [ ] Submitting with a negative or zero amount shows a validation error
- [ ] Submitting with an invalid category shows a validation error
- [ ] After a failed submission, the form retains the previously entered values
- [ ] No raw SQL in `app.py` — all DB work goes through `database/db.py`
- [ ] All URLs in the template use `url_for()` — no hardcoded paths
- [ ] A "Cancel" link on the form returns the user to `/profile`

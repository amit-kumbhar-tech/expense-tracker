# Spec: Date Filter for Profile Page

## Overview
This step replaces all hardcoded data on the profile page with real database queries and adds a date-range filter so users can slice their expense history by time period. Until now the profile page displayed static demo values; this step wires it to the logged-in user's actual rows in the `expenses` table. A filter bar lets the user pick a preset window (This Month, Last 3 Months, This Year, All Time) or supply a custom from/to date. Summary stats (total spent, transaction count, top category) and the transaction table update accordingly. Access to the profile page is restricted to logged-in users.

## Depends on
- Step 01 — database setup (`get_db()`, `init_db()`, `seed_db()`, `expenses` table)
- Step 02 — registration (user records exist in DB)
- Step 03 — login/logout (session management, `session['user_id']`)
- Step 04 — profile page design (template structure and CSS to build upon)

## Routes
- `GET /profile` — renders profile page with real user data and filtered expenses — logged-in only

No new routes. The existing `/profile` route is updated.

## Database changes
No schema changes. All required tables and columns already exist:
- `users`: `id`, `name`, `email`, `created_at`
- `expenses`: `id`, `user_id`, `amount`, `category`, `date`, `description`, `created_at`

## Templates
- **Modify:** `templates/profile.html`
  - Replace every hardcoded value with a Jinja2 variable
  - Add a filter bar above the transaction table with preset buttons (This Month, Last 3 Months, This Year, All Time) and a custom date-range form (two `<input type="date">` fields + Apply button)
  - Active preset button gets a highlighted state driven by a template variable
  - Redirect to `/login` (via `url_for`) when the user is not logged in

## Files to change
- `app.py` — update `GET /profile` route:
  - Guard: redirect to `/login` if `session.get('user_id')` is falsy
  - Parse query params: `filter` (preset name) and `from_date` / `to_date` (custom range)
  - Delegate all DB work to helpers in `database/db.py`
  - Pass `user`, `expenses`, `stats`, `active_filter`, `from_date`, `to_date` to template
- `database/db.py` — add new helper functions (see below)
- `templates/profile.html` — replace hardcoded values, add filter bar
- `static/css/profile.css` — add styles for filter bar and active-filter state (create if it doesn't exist yet; add to existing file if it does)

## Files to create
- None (all changes go into existing files)

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — use `sqlite3` via `get_db()` only
- Parameterised queries only — never interpolate variables into SQL strings
- Passwords are never read or returned — never `SELECT password_hash` in profile queries
- Use CSS variables — never hardcode hex colour values in CSS
- All templates extend `base.html`
- Date arithmetic done in SQL (`WHERE date BETWEEN ? AND ?`) — not in Python
- Preset date ranges computed in the route function using `datetime` from the standard library — no extra packages
- If `filter` param is absent or unrecognised, default to `"this_month"`
- Custom range: if only one of `from_date` / `to_date` is supplied, ignore both and fall back to the active preset
- The profile page must redirect (302) to `/login` when no session exists — never show a 401 page
- Stats (total, count, top category) must be computed from the **filtered** expense set, not all-time data

## DB helpers to add in `database/db.py`
```python
def get_expenses_for_user(user_id, from_date, to_date):
    """Return all expenses for user_id between from_date and to_date (inclusive, YYYY-MM-DD strings)."""

def get_expense_stats(user_id, from_date, to_date):
    """Return dict with keys: total_spent, transaction_count, top_category."""
```

## Definition of done
- [ ] Visiting `/profile` while logged out redirects to `/login`
- [ ] Visiting `/profile` while logged in shows the real logged-in user's name and email (not "Demo User")
- [ ] "Member Since" reflects the user's actual `created_at` date from the DB
- [ ] Default view shows "This Month" filter active, displaying only current-month expenses
- [ ] Clicking "Last 3 Months" re-renders the page with only the last 90 days of expenses
- [ ] Clicking "This Year" re-renders the page with only the current calendar year's expenses
- [ ] Clicking "All Time" re-renders the page with every expense for the user
- [ ] Entering a custom from/to date and clicking Apply filters the table to that exact range
- [ ] Summary stats (total spent, transaction count, top category) reflect the **filtered** data, not all-time totals
- [ ] Category breakdown percentages add up to 100% (or 0% with an empty state message when no expenses exist)
- [ ] Transaction table shows "No expenses found" (or similar) when the filtered range returns zero rows
- [ ] The active preset button is visually distinguished from inactive ones
- [ ] All URLs in the template use `url_for()` — no hardcoded paths
- [ ] No raw SQL in `app.py` — all queries go through `database/db.py` helpers

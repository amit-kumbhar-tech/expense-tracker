# Spec: Edit Expense

## Overview
This step implements the full "edit expense" flow: a logged-in user can click an edit button next to any of their expenses on the profile page, be taken to a pre-filled form showing that expense's current values, make changes, and submit to update the record in the database. The existing route stub returns a plain string; this step replaces it with a real GET/POST handler backed by two new DB helpers. Ownership is enforced — a user cannot edit another user's expense. On success the user is redirected back to the profile page.

## Depends on
- Step 01 — database setup (`get_db()`, `expenses` table schema)
- Step 03 — login/logout (session management, `session['user_id']`)
- Step 04/05 — profile page (where the edit link lives and where the user returns after editing)
- Step 06 — add expense (established the form pattern and `_VALID_CATEGORIES` constant this step reuses)

## Routes
- `GET /expenses/<int:id>/edit` — render the edit form pre-filled with the existing expense — logged-in only
- `POST /expenses/<int:id>/edit` — validate and persist the updated expense, then redirect to `/profile` — logged-in only

## Database changes
No schema changes. The `expenses` table already has all required columns.

Two new DB helpers must be added to `database/db.py`:
- `get_expense_by_id(expense_id)` — fetch a single expense row by primary key
- `update_expense(expense_id, amount, category, date, description)` — update all editable fields

## Templates
- **Create:** `templates/edit_expense.html`
  - Extends `base.html`
  - Form with the same fields as `add_expense.html`: amount, category (select), date, description
  - All fields pre-populated with the existing expense's values
  - Inline validation error display on re-render
  - Cancel link back to `/profile` using `url_for`
- **Modify:** `templates/profile.html`
  - Add an "Edit" link/button next to each expense row in the transaction list
  - Link must use `url_for('edit_expense', id=expense.id)`

## Files to change
- `app.py`
  - Replace the `edit_expense` stub with a full GET/POST handler
  - Guard: redirect to `/login` if `session.get('user_id')` is falsy
  - GET: call `get_expense_by_id(id)`, `abort(404)` if not found, `abort(403)` if `expense['user_id'] != session['user_id']`, render `edit_expense.html` with expense values pre-filled
  - POST: validate fields (same rules as add), call `update_expense(...)`, redirect to `url_for('profile')` on success; re-render with error on failure
  - Import `get_expense_by_id` and `update_expense` from `database.db`
  - Add `methods=["GET", "POST"]` to the route decorator
- `database/db.py`
  - Add `get_expense_by_id(expense_id)` helper
  - Add `update_expense(expense_id, amount, category, date, description)` helper
- `templates/profile.html`
  - Add Edit link per expense row

## Files to create
- `templates/edit_expense.html` — the edit-expense form template
- `static/css/edit_expense.css` — page-specific styles (can mirror `add_expense.css` structure)

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — use `sqlite3` via `get_db()` only
- Parameterised queries only — never interpolate variables into SQL strings
- Passwords are never touched in this step
- Use CSS variables — never hardcode hex colour values in CSS
- All templates extend `base.html`
- The route must redirect (302) to `/login` if no session — never show a 401
- `abort(404)` if the expense ID does not exist
- `abort(403)` if the expense's `user_id` does not match `session['user_id']` — never let a user edit another user's expense
- Validation rules are identical to add expense: positive amount ≤ 1,000,000; category in `_VALID_CATEGORIES`; date is valid ISO format and not in the future; description ≤ 200 characters
- On success, redirect to `url_for('profile')` — never re-render the form
- On validation failure, re-render `edit_expense.html` with the submitted values pre-filled and an error message

## DB helpers to add in `database/db.py`
```python
def get_expense_by_id(expense_id):
    """Return the expense row with the given id, or None if not found."""

def update_expense(expense_id, amount, category, date, description):
    """Update all editable fields on an existing expense row."""
```

## Definition of done
- [ ] `GET /expenses/<id>/edit` while logged out redirects to `/login`
- [ ] `GET /expenses/<id>/edit` for a non-existent ID returns 404
- [ ] `GET /expenses/<id>/edit` for an expense belonging to another user returns 403
- [ ] `GET /expenses/<id>/edit` while logged in renders the form with all fields pre-filled from the database
- [ ] Submitting a valid edit updates the row in the `expenses` table and redirects to `/profile`
- [ ] The updated values are visible on the profile page after redirect
- [ ] Submitting with an invalid amount shows a validation error and does not update the row
- [ ] Submitting with a future date shows a validation error
- [ ] After a failed submission, the form retains the submitted (not original) values
- [ ] An "Edit" link appears next to each expense on the profile page and navigates to the correct edit URL
- [ ] No raw SQL in `app.py` — all DB work goes through `database/db.py`
- [ ] All URLs in the template use `url_for()` — no hardcoded paths
- [ ] A "Cancel" link on the form returns the user to `/profile`

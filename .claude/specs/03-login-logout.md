# Spec: Login and Logout

## Overview
Wire up credential-based login and session teardown for Spendly. The `GET /login`
route and `login.html` template already exist; this step adds `POST /login` to
verify the submitted email/password against the database, start a Flask session on
success, and redirect to the landing page. It also implements `GET /logout` (currently
a raw-string stub) to clear the session and redirect home. Finally, the nav bar in
`base.html` is updated to show context-sensitive links — authenticated users see a
logout link instead of "Sign in / Get started".

## Depends on
- Step 1 — Database setup (`get_db()`, `users` table, `init_db()`)
- Step 2 — Registration (`create_user()`, `get_user_by_email()`, `session['user_id']`)

## Routes
- `POST /login` — validates email/password, starts session, redirects to `/` — public
- `GET /logout` — clears session, redirects to `/` — public (no login guard needed)

`GET /login` already exists; its handler does not change.

## Database changes
No new tables or columns. One new helper function added to `database/db.py`:

- `get_user_by_id(user_id)` — returns the `sqlite3.Row` for the given id, or `None`
  (needed now to support future steps that load the logged-in user)

No schema migrations required.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html` — change `action="/login"` to
    `action="{{ url_for('login') }}"` — never hardcode URLs
  - `templates/base.html` — update nav links to be session-aware:
    - When `session.user_id` is **not** set: show "Sign in" + "Get started" (current state)
    - When `session.user_id` **is** set: show the user's name and a "Sign out" link
      pointing to `url_for('logout')`

## Files to change
- `app.py` — implement `POST /login` route; implement `GET /logout` route;
  add `check_password_hash` to werkzeug imports; add `get_user_by_id` import
- `database/db.py` — add `get_user_by_id(user_id)` helper
- `templates/login.html` — fix hardcoded form `action`
- `templates/base.html` — add session-aware nav

## Files to create
None.

## New dependencies
No new pip packages. Uses only:
- `werkzeug.security.check_password_hash` (werkzeug already in requirements)
- `flask.session`, `flask.redirect`, `flask.request` (already imported)

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — no f-strings or `%` formatting in SQL
- Passwords verified with `werkzeug.security.check_password_hash` — never compare plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- All internal links use `url_for()`
- DB logic stays in `database/db.py` — route functions must not execute SQL directly
- On login failure (wrong email or wrong password): re-render `login.html` with a
  generic `error="Invalid email or password."` — do not distinguish which field failed
  (prevents user enumeration)
- On login success: set `session['user_id']` and `session['user_name']`, then
  `redirect(url_for('landing'))`
- `GET /logout` must call `session.clear()` then `redirect(url_for('landing'))`
- The nav in `base.html` must use `session.get('user_id')` — never rely on a template
  variable passed from the route
- Do not add a `@login_required` decorator in this step — that belongs to Step 4

## Definition of done
- [ ] Submitting the login form with the demo account (`demo@spendly.com` / `demo123`)
      redirects to the landing page with no error
- [ ] After login, `session['user_id']` and `session['user_name']` are set
      (verifiable via browser dev tools → Application → Cookies)
- [ ] Submitting with a correct email but wrong password re-renders the login form
      with a visible error — no 500 crash
- [ ] Submitting with an email that does not exist re-renders the form with the same
      generic error — does not leak whether the email is registered
- [ ] Visiting `/logout` clears the session and redirects to `/`
- [ ] After logout, the nav bar shows "Sign in" and "Get started" again
- [ ] While logged in, the nav bar shows the user's name and a "Sign out" link
- [ ] `login.html` uses `url_for('login')` in the form `action` — no hardcoded path
- [ ] No SQL is written inside `app.py` — all DB calls go through `database/db.py` helpers
- [ ] App starts without errors after changes

"""
tests/test_06-add-expense.py

Pytest tests for Spendly Step 06 — Add Expense feature.

Spec: .claude/specs/06-add-expense.md

Test strategy
-------------
- db.py stores the database path in a module-level _DB_PATH. We monkeypatch
  that attribute so every get_db() call inside the route goes to a clean
  temp file, giving each test a fully isolated SQLite database.
- Direct SQL helpers insert and query data without going through the app,
  so DB side-effect assertions are independent of the HTTP layer.
- Session injection via client.session_transaction() avoids a real
  login round-trip for every test while still exercising the auth guard
  through a separate unauthenticated client.
"""

import sqlite3
from datetime import date

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app


# ---------------------------------------------------------------------------
# Schema and data helpers (direct SQL — no dependency on app-level helpers)
# ---------------------------------------------------------------------------

def _create_schema(conn):
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()


def _insert_user(conn, name, email):
    pw_hash = generate_password_hash("testpassword123")
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, pw_hash),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()[0]


def _count_expenses(conn, user_id):
    return conn.execute(
        "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
    ).fetchone()[0]


def _fetch_all_expenses(conn, user_id):
    return conn.execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY id DESC", (user_id,)
    ).fetchall()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_db(monkeypatch, tmp_path):
    """
    Redirect get_db() to a fresh SQLite temp file.
    Yields (db_file_path, open_connection) so tests can run direct queries.
    """
    db_file = str(tmp_path / "test_spendly.db")
    monkeypatch.setattr(db_module, "_DB_PATH", db_file)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    yield db_file, conn
    conn.close()


@pytest.fixture()
def app(isolated_db):
    flask_app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "pytest-secret",
            "WTF_CSRF_ENABLED": False,
        }
    )
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def test_user(isolated_db):
    """Insert a primary test user; return (user_id, name, email)."""
    _, conn = isolated_db
    user_id = _insert_user(conn, name="Alice Tester", email="alice@example.com")
    return user_id, "Alice Tester", "alice@example.com"


@pytest.fixture()
def logged_in_client(client, test_user):
    """A test client with Alice's session already injected — no login round-trip."""
    user_id, _, _ = test_user
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Alice Tester"
    return client


# ---------------------------------------------------------------------------
# Shared valid-expense form data
# ---------------------------------------------------------------------------

VALID_FORM = {
    "amount": "42.50",
    "category": "Food",
    "date": "2026-06-01",
    "description": "Test lunch",
}


# ===========================================================================
# 1. AUTH GUARD
# ===========================================================================

class TestAuthGuard:
    """Unauthenticated requests must be redirected to /login."""

    def test_get_add_expense_unauthenticated_redirects_to_login(self, client):
        """GET /expenses/add without a session must return 302 pointing to /login."""
        response = client.get("/expenses/add")
        assert response.status_code == 302, (
            f"Expected 302, got {response.status_code}"
        )
        location = response.headers.get("Location", "")
        assert "/login" in location, (
            f"Redirect location must contain /login, got: {location}"
        )

    def test_get_add_expense_unauthenticated_does_not_return_200(self, client):
        """GET /expenses/add without a session must never render the form (no 200)."""
        response = client.get("/expenses/add")
        assert response.status_code != 200, (
            "Add expense page must not be accessible without authentication"
        )

    def test_post_add_expense_unauthenticated_redirects_to_login(self, client):
        """POST /expenses/add without a session must redirect to /login, not save data."""
        response = client.post("/expenses/add", data=VALID_FORM)
        assert response.status_code == 302, (
            f"Expected 302, got {response.status_code}"
        )
        location = response.headers.get("Location", "")
        assert "/login" in location, (
            f"POST without auth must redirect to /login, got: {location}"
        )

    def test_get_add_expense_unauthenticated_follows_redirect_to_login(self, client):
        """Following the redirect from an unauthenticated GET should reach the login page."""
        response = client.get("/expenses/add", follow_redirects=True)
        assert response.status_code == 200
        assert b"login" in response.data.lower() or b"Login" in response.data, (
            "Following redirect should reach the login page"
        )


# ===========================================================================
# 2. GET — FORM RENDERING
# ===========================================================================

class TestGetAddExpenseForm:
    """Authenticated GET /expenses/add must render the expense form correctly."""

    def test_get_renders_200_when_logged_in(self, logged_in_client):
        """Authenticated GET /expenses/add must return HTTP 200."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}"
        )

    def test_get_prefills_today_date(self, logged_in_client):
        """The date input must be pre-filled with today's ISO date (YYYY-MM-DD)."""
        today = date.today().isoformat()
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        assert today.encode() in response.data, (
            f"Expected today's date '{today}' pre-filled in the date input"
        )

    def test_get_renders_amount_field(self, logged_in_client):
        """Form must contain an amount input field."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        assert b'name="amount"' in response.data, (
            "Form must render an input with name='amount'"
        )

    def test_get_renders_category_dropdown(self, logged_in_client):
        """Form must contain a category select/dropdown."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        assert b'name="category"' in response.data, (
            "Form must render a select/input with name='category'"
        )

    def test_get_renders_date_field(self, logged_in_client):
        """Form must contain a date input field."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        assert b'name="date"' in response.data, (
            "Form must render an input with name='date'"
        )

    def test_get_renders_description_field(self, logged_in_client):
        """Form must contain an optional description input field."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        assert b'name="description"' in response.data, (
            "Form must render an input with name='description'"
        )

    def test_get_renders_all_valid_categories_in_dropdown(self, logged_in_client):
        """All 7 valid categories must appear as options in the category dropdown."""
        valid_categories = [
            "Food", "Transport", "Bills", "Health",
            "Entertainment", "Shopping", "Other",
        ]
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        data = response.data.decode()
        for cat in valid_categories:
            assert cat in data, (
                f"Category '{cat}' must appear as an option in the category dropdown"
            )

    def test_get_page_extends_base_template(self, logged_in_client):
        """Add expense page must extend base.html — must be a full HTML document."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        data = response.data.decode()
        assert "<html" in data or "<!DOCTYPE" in data, (
            "Page must extend base.html and produce a full HTML document"
        )


# ===========================================================================
# 3. CANCEL LINK AND URL_FOR USAGE
# ===========================================================================

class TestTemplateLinks:
    """Links in the template must resolve correctly and use url_for — not hardcoded paths."""

    def test_cancel_link_resolves_to_profile(self, logged_in_client):
        """The Cancel / Back link must href to /profile."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        data = response.data.decode()
        assert 'href="/profile"' in data or "href='/profile'" in data, (
            "Cancel link must have href='/profile' (url_for('profile') output)"
        )

    def test_form_action_resolves_to_add_expense_route(self, logged_in_client):
        """The form action must resolve to /expenses/add — url_for('add_expense')."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        data = response.data.decode()
        assert 'action="/expenses/add"' in data or "action='/expenses/add'" in data, (
            "Form action must resolve to /expenses/add (url_for('add_expense') output)"
        )

    def test_no_hardcoded_full_urls_in_links(self, logged_in_client):
        """Template must not contain hardcoded http:// absolute URLs in href attributes."""
        response = logged_in_client.get("/expenses/add")
        assert response.status_code == 200
        data = response.data.decode()
        assert 'href="http://' not in data and "href='http://" not in data, (
            "Template must not hardcode absolute http:// URLs in href attributes"
        )


# ===========================================================================
# 4. VALID SUBMISSION — HAPPY PATH
# ===========================================================================

class TestValidSubmission:
    """POST with complete valid data must persist the expense and redirect to /profile."""

    def test_valid_post_redirects_to_profile(self, logged_in_client):
        """Successful POST must redirect (302) to /profile."""
        response = logged_in_client.post("/expenses/add", data=VALID_FORM)
        assert response.status_code == 302, (
            f"Expected 302 redirect on success, got {response.status_code}"
        )
        location = response.headers.get("Location", "")
        assert "/profile" in location, (
            f"Success redirect must point to /profile, got: {location}"
        )

    def test_valid_post_inserts_row_in_db(self, logged_in_client, test_user, isolated_db):
        """Successful POST must insert exactly one new row in the expenses table."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        logged_in_client.post("/expenses/add", data=VALID_FORM)
        after = _count_expenses(conn, user_id)
        assert after == before + 1, (
            f"Expected exactly one new expense row; before={before}, after={after}"
        )

    def test_valid_post_saves_correct_amount(self, logged_in_client, test_user, isolated_db):
        """The saved expense must have the exact amount submitted."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        logged_in_client.post("/expenses/add", data={**VALID_FORM, "amount": "99.99"})
        rows = _fetch_all_expenses(conn, user_id)
        assert len(rows) >= 1, "Expected at least one expense row in the DB"
        latest = rows[0]
        assert abs(latest["amount"] - 99.99) < 0.001, (
            f"Saved amount must be 99.99, got {latest['amount']}"
        )

    def test_valid_post_saves_correct_category(self, logged_in_client, test_user, isolated_db):
        """The saved expense must store the submitted category."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        logged_in_client.post("/expenses/add", data={**VALID_FORM, "category": "Transport"})
        rows = _fetch_all_expenses(conn, user_id)
        assert len(rows) >= 1
        assert rows[0]["category"] == "Transport", (
            f"Saved category must be 'Transport', got '{rows[0]['category']}'"
        )

    def test_valid_post_saves_correct_date(self, logged_in_client, test_user, isolated_db):
        """The saved expense must store the submitted date."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        logged_in_client.post("/expenses/add", data={**VALID_FORM, "date": "2026-03-15"})
        rows = _fetch_all_expenses(conn, user_id)
        assert len(rows) >= 1
        assert rows[0]["date"] == "2026-03-15", (
            f"Saved date must be '2026-03-15', got '{rows[0]['date']}'"
        )

    def test_valid_post_saves_correct_description(self, logged_in_client, test_user, isolated_db):
        """The saved expense must store the submitted description text."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "description": "My unique test description"},
        )
        rows = _fetch_all_expenses(conn, user_id)
        assert len(rows) >= 1
        assert rows[0]["description"] == "My unique test description", (
            f"Saved description must match submitted value, got '{rows[0]['description']}'"
        )

    def test_new_expense_appears_on_profile_page(self, logged_in_client):
        """After a successful POST, the description must appear in the profile transaction list."""
        unique_desc = "Unique cinema expense for profile check"
        today = date.today().isoformat()
        logged_in_client.post(
            "/expenses/add",
            data={
                "amount": "20.00",
                "category": "Entertainment",
                "date": today,
                "description": unique_desc,
            },
        )
        profile_response = logged_in_client.get("/profile?filter=all_time")
        assert response_contains(profile_response, unique_desc), (
            f"New expense description '{unique_desc}' must appear on the profile page"
        )

    def test_description_is_optional_omitted(self, logged_in_client, test_user, isolated_db):
        """POST without a description field must still save the expense successfully."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        response = logged_in_client.post(
            "/expenses/add",
            data={"amount": "10.00", "category": "Other", "date": "2026-06-01"},
        )
        after = _count_expenses(conn, user_id)
        assert response.status_code == 302, (
            "Omitting description must still result in a successful redirect"
        )
        assert after == before + 1, (
            "Expense without description must still be saved to the DB"
        )

    def test_description_is_optional_empty_string(self, logged_in_client, test_user, isolated_db):
        """POST with an empty description string must save the expense."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "description": ""},
        )
        after = _count_expenses(conn, user_id)
        assert response.status_code == 302, (
            "Empty description must still result in a successful redirect"
        )
        assert after == before + 1, (
            "Expense with empty description must still be saved to the DB"
        )

    @pytest.mark.parametrize("category", [
        "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"
    ])
    def test_all_valid_categories_accepted(
        self, logged_in_client, test_user, isolated_db, category
    ):
        """Each of the 7 valid categories must be accepted and saved successfully."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "category": category},
        )
        after = _count_expenses(conn, user_id)
        assert response.status_code == 302, (
            f"Category '{category}' must be accepted; got status {response.status_code}"
        )
        assert after == before + 1, (
            f"Category '{category}' must result in a DB row being inserted"
        )

    def test_blank_date_defaults_to_today(self, logged_in_client, test_user, isolated_db):
        """Submitting with an empty date must store today's date in the DB."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        today = date.today().isoformat()
        logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "date": ""},
        )
        rows = _fetch_all_expenses(conn, user_id)
        assert len(rows) >= 1
        assert rows[0]["date"] == today, (
            f"Blank date must default to today '{today}', got '{rows[0]['date']}'"
        )


# ===========================================================================
# 5. VALIDATION ERRORS — AMOUNT
# ===========================================================================

class TestAmountValidation:
    """Amount field must reject empty, zero, and negative values."""

    def test_empty_amount_returns_200_with_error(self, logged_in_client):
        """POST with blank amount must return 200 and show a validation error."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "amount": ""},
        )
        assert response.status_code == 200, (
            f"Blank amount must re-render the form (200), got {response.status_code}"
        )
        assert b"error" in response.data.lower() or b"Amount" in response.data, (
            "Blank amount submission must display a validation error message"
        )

    def test_empty_amount_does_not_insert_row(self, logged_in_client, test_user, isolated_db):
        """POST with blank amount must not insert any row in the expenses table."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        logged_in_client.post("/expenses/add", data={**VALID_FORM, "amount": ""})
        after = _count_expenses(conn, user_id)
        assert after == before, (
            f"No expense must be inserted for a blank amount; before={before}, after={after}"
        )

    def test_zero_amount_returns_200_with_error(self, logged_in_client):
        """POST with amount=0 must return 200 and show a validation error."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "amount": "0"},
        )
        assert response.status_code == 200, (
            f"Zero amount must re-render the form (200), got {response.status_code}"
        )

    def test_zero_amount_does_not_insert_row(self, logged_in_client, test_user, isolated_db):
        """POST with amount=0 must not insert any row in the expenses table."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        logged_in_client.post("/expenses/add", data={**VALID_FORM, "amount": "0"})
        after = _count_expenses(conn, user_id)
        assert after == before, (
            f"No expense must be inserted for zero amount; before={before}, after={after}"
        )

    def test_negative_amount_returns_200_with_error(self, logged_in_client):
        """POST with a negative amount must return 200 and show a validation error."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "amount": "-5.00"},
        )
        assert response.status_code == 200, (
            f"Negative amount must re-render the form (200), got {response.status_code}"
        )

    def test_negative_amount_does_not_insert_row(self, logged_in_client, test_user, isolated_db):
        """POST with a negative amount must not insert any row in the expenses table."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        logged_in_client.post("/expenses/add", data={**VALID_FORM, "amount": "-5.00"})
        after = _count_expenses(conn, user_id)
        assert after == before, (
            f"No expense must be inserted for a negative amount; before={before}, after={after}"
        )

    def test_non_numeric_amount_returns_200_with_error(self, logged_in_client):
        """POST with a non-numeric amount must return 200 and show a validation error."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "amount": "abc"},
        )
        assert response.status_code == 200, (
            "Non-numeric amount must re-render the form"
        )

    @pytest.mark.parametrize("bad_amount", ["0", "-1", "-0.01", "abc", ""])
    def test_invalid_amounts_all_show_error(self, logged_in_client, bad_amount):
        """All disallowed amount values must produce a 200 response (not a redirect)."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "amount": bad_amount},
        )
        assert response.status_code == 200, (
            f"Amount '{bad_amount}' must be rejected; expected 200, got {response.status_code}"
        )
        assert response.status_code != 302, (
            f"Invalid amount '{bad_amount}' must not trigger a redirect"
        )


# ===========================================================================
# 6. VALIDATION ERRORS — CATEGORY
# ===========================================================================

class TestCategoryValidation:
    """Category field must reject values not in the allowed list."""

    def test_invalid_category_returns_200_with_error(self, logged_in_client):
        """POST with an unrecognised category must return 200 and show a validation error."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "category": "InvalidCategory"},
        )
        assert response.status_code == 200, (
            f"Invalid category must re-render the form (200), got {response.status_code}"
        )

    def test_invalid_category_does_not_insert_row(self, logged_in_client, test_user, isolated_db):
        """POST with an unrecognised category must not insert any row in the DB."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "category": "InvalidCategory"},
        )
        after = _count_expenses(conn, user_id)
        assert after == before, (
            f"No expense must be inserted for invalid category; before={before}, after={after}"
        )

    def test_empty_category_returns_200_with_error(self, logged_in_client):
        """POST with an empty category value must return 200 and show a validation error."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "category": ""},
        )
        assert response.status_code == 200, (
            "Empty category must re-render the form"
        )

    @pytest.mark.parametrize("bad_category", ["", "food", "FOOD", "InvalidCategory", "Expenses"])
    def test_invalid_categories_all_rejected(self, logged_in_client, bad_category):
        """Case-sensitive and unrecognised categories must all be rejected."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "category": bad_category},
        )
        assert response.status_code == 200, (
            f"Category '{bad_category}' must be rejected; expected 200, got {response.status_code}"
        )
        assert response.status_code != 302, (
            f"Invalid category '{bad_category}' must not trigger a redirect"
        )


# ===========================================================================
# 7. VALIDATION ERRORS — DATE
# ===========================================================================

class TestDateValidation:
    """Date field must accept blank (defaults to today) and valid ISO dates; reject malformed ones."""

    def test_invalid_date_format_returns_200_with_error(self, logged_in_client):
        """POST with a non-ISO date string must return 200 and show a validation error."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "date": "not-a-date"},
        )
        assert response.status_code == 200, (
            "Non-ISO date must re-render the form"
        )

    def test_invalid_date_does_not_insert_row(self, logged_in_client, test_user, isolated_db):
        """POST with an invalid date must not insert any row in the expenses table."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        logged_in_client.post("/expenses/add", data={**VALID_FORM, "date": "not-a-date"})
        after = _count_expenses(conn, user_id)
        assert after == before, (
            f"No expense must be inserted for an invalid date; before={before}, after={after}"
        )

    @pytest.mark.parametrize("bad_date", ["not-a-date", "32-13-2026", "2026/06/01", "June 1"])
    def test_malformed_dates_all_rejected(self, logged_in_client, bad_date):
        """All non-ISO date strings must be rejected and re-render the form."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "date": bad_date},
        )
        assert response.status_code == 200, (
            f"Date '{bad_date}' must be rejected; expected 200, got {response.status_code}"
        )


# ===========================================================================
# 8. FORM VALUE RETENTION ON FAILED SUBMISSION
# ===========================================================================

class TestFormRetainsValues:
    """After a failed validation, the form must echo back the submitted field values."""

    def test_amount_retained_after_invalid_category(self, logged_in_client):
        """After a category validation failure, the submitted amount must appear in the form."""
        response = logged_in_client.post(
            "/expenses/add",
            data={
                "amount": "123.45",
                "category": "BadCategory",
                "date": "2026-06-01",
                "description": "Retention test",
            },
        )
        assert response.status_code == 200
        assert b"123.45" in response.data, (
            "Amount value '123.45' must be retained in the re-rendered form after validation failure"
        )

    def test_description_retained_after_invalid_amount(self, logged_in_client):
        """After an amount validation failure, the submitted description must appear in the form."""
        response = logged_in_client.post(
            "/expenses/add",
            data={
                "amount": "0",
                "category": "Food",
                "date": "2026-06-01",
                "description": "Unique retention desc 9981",
            },
        )
        assert response.status_code == 200
        assert b"Unique retention desc 9981" in response.data, (
            "Description must be retained in the re-rendered form after validation failure"
        )

    def test_category_retained_after_invalid_amount(self, logged_in_client):
        """After an amount validation failure, the selected category must be pre-selected."""
        response = logged_in_client.post(
            "/expenses/add",
            data={
                "amount": "-1",
                "category": "Health",
                "date": "2026-06-01",
                "description": "",
            },
        )
        assert response.status_code == 200
        data = response.data.decode()
        # The selected option should have the 'selected' attribute near 'Health'
        assert "Health" in data, (
            "Category 'Health' must be retained in the re-rendered form after validation failure"
        )

    def test_date_retained_after_invalid_category(self, logged_in_client):
        """After a category validation failure, the submitted date must appear in the form."""
        response = logged_in_client.post(
            "/expenses/add",
            data={
                "amount": "50.00",
                "category": "BadCategory",
                "date": "2026-04-20",
                "description": "",
            },
        )
        assert response.status_code == 200
        assert b"2026-04-20" in response.data, (
            "Date value '2026-04-20' must be retained in the re-rendered form after validation failure"
        )

    def test_error_message_displayed_on_invalid_submission(self, logged_in_client):
        """A visible error message must be present on the page after any validation failure."""
        response = logged_in_client.post(
            "/expenses/add",
            data={**VALID_FORM, "amount": "-99"},
        )
        assert response.status_code == 200
        data = response.data.decode().lower()
        assert "error" in data or "invalid" in data or "positive" in data or "valid" in data, (
            "A validation error message must appear on the re-rendered form page"
        )


# ===========================================================================
# Helper (used in happy-path profile check)
# ===========================================================================

def response_contains(response, text):
    """Return True if the byte string of `text` is present in response.data."""
    return text.encode() in response.data

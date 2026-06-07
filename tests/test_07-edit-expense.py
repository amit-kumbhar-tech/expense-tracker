"""
tests/test_07-edit-expense.py

Pytest tests for Spendly Step 07 — Edit Expense feature.

Spec: .claude/specs/07-edit-expense.md

Test strategy
-------------
- db.py stores the database path in a module-level _DB_PATH.  We monkeypatch
  that attribute so every get_db() call inside the route goes to a clean
  temp file, giving each test a fully isolated SQLite database.
- Direct SQL helpers insert and query data without going through the app,
  so DB side-effect assertions are independent of the HTTP layer.
- Two test users (Alice and Bob) are available so the 403-ownership tests
  can verify that a user cannot edit another user's expense.
- Session injection via client.session_transaction() avoids a real login
  round-trip while still exercising the auth guard through a separate
  unauthenticated client.
"""

import sqlite3
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app

# ---------------------------------------------------------------------------
# Schema and direct-SQL helpers (no dependency on app-level helpers)
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
    return conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]


def _insert_expense(conn, user_id, amount, category, exp_date, description=""):
    cursor = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, exp_date, description or None),
    )
    conn.commit()
    return cursor.lastrowid


def _fetch_expense(conn, expense_id):
    return conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()


def _count_expenses(conn, user_id):
    return conn.execute(
        "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(monkeypatch, tmp_path):
    """
    Redirect get_db() to a fresh SQLite temp file for every test.
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
def alice(isolated_db):
    """Insert primary test user Alice; return (user_id, name, email)."""
    _, conn = isolated_db
    user_id = _insert_user(conn, name="Alice Tester", email="alice@example.com")
    return user_id, "Alice Tester", "alice@example.com"


@pytest.fixture()
def bob(isolated_db):
    """Insert a second user Bob so ownership tests can be exercised."""
    _, conn = isolated_db
    user_id = _insert_user(conn, name="Bob Other", email="bob@example.com")
    return user_id, "Bob Other", "bob@example.com"


@pytest.fixture()
def alice_expense(alice, isolated_db):
    """Insert one expense owned by Alice; return the expense id."""
    user_id, _, _ = alice
    _, conn = isolated_db
    expense_id = _insert_expense(
        conn,
        user_id,
        amount=50.00,
        category="Food",
        exp_date="2026-05-10",
        description="Original lunch",
    )
    return expense_id


@pytest.fixture()
def bob_expense(bob, isolated_db):
    """Insert one expense owned by Bob; return the expense id."""
    user_id, _, _ = bob
    _, conn = isolated_db
    expense_id = _insert_expense(
        conn,
        user_id,
        amount=75.00,
        category="Transport",
        exp_date="2026-05-15",
        description="Bob bus pass",
    )
    return expense_id


@pytest.fixture()
def alice_client(client, alice):
    """A test client with Alice's session already injected — no login round-trip."""
    user_id, _, _ = alice
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Alice Tester"
    return client


@pytest.fixture()
def bob_client(client, bob):
    """A test client with Bob's session already injected."""
    user_id, _, _ = bob
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Bob Other"
    return client


# ---------------------------------------------------------------------------
# Shared valid edit-form payload (always valid according to the spec)
# ---------------------------------------------------------------------------

VALID_EDIT_FORM = {
    "amount": "99.00",
    "category": "Transport",
    "date": "2026-05-20",
    "description": "Updated description",
}


# ===========================================================================
# 1. AUTH GUARD
# ===========================================================================


class TestAuthGuard:
    """Unauthenticated requests to GET and POST /expenses/<id>/edit must 302 to /login."""

    def test_get_edit_expense_unauthenticated_redirects_to_login(
        self, client, alice_expense
    ):
        """GET /expenses/<id>/edit without a session must return 302 pointing to /login."""
        response = client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 302, f"Expected 302, got {response.status_code}"
        location = response.headers.get("Location", "")
        assert (
            "/login" in location
        ), f"Redirect location must contain /login, got: {location}"

    def test_get_edit_expense_unauthenticated_does_not_render_form(
        self, client, alice_expense
    ):
        """GET /expenses/<id>/edit without a session must never return 200 (form page)."""
        response = client.get(f"/expenses/{alice_expense}/edit")
        assert (
            response.status_code != 200
        ), "Edit expense page must not be accessible without authentication"

    def test_get_edit_expense_unauthenticated_follows_redirect_to_login(
        self, client, alice_expense
    ):
        """Following the redirect from unauthenticated GET should reach the login page."""
        response = client.get(f"/expenses/{alice_expense}/edit", follow_redirects=True)
        assert response.status_code == 200
        assert (
            b"login" in response.data.lower() or b"Login" in response.data
        ), "Following redirect should reach the login page"

    def test_post_edit_expense_unauthenticated_redirects_to_login(
        self, client, alice_expense
    ):
        """POST /expenses/<id>/edit without a session must redirect to /login."""
        response = client.post(f"/expenses/{alice_expense}/edit", data=VALID_EDIT_FORM)
        assert (
            response.status_code == 302
        ), f"Expected 302 redirect, got {response.status_code}"
        location = response.headers.get("Location", "")
        assert (
            "/login" in location
        ), f"POST without auth must redirect to /login, got: {location}"

    def test_post_edit_expense_unauthenticated_does_not_modify_db(
        self, client, alice_expense, isolated_db
    ):
        """POST /expenses/<id>/edit without auth must not change the expense in the DB."""
        _, conn = isolated_db
        original = _fetch_expense(conn, alice_expense)
        client.post(f"/expenses/{alice_expense}/edit", data=VALID_EDIT_FORM)
        after = _fetch_expense(conn, alice_expense)
        assert (
            original["amount"] == after["amount"]
        ), "Unauthenticated POST must not mutate the expense amount"
        assert (
            original["description"] == after["description"]
        ), "Unauthenticated POST must not mutate the expense description"


# ===========================================================================
# 2. 404 — NON-EXISTENT EXPENSE ID
# ===========================================================================


class TestNotFound:
    """Requests with an expense ID that does not exist in the DB must return 404."""

    def test_get_non_existent_expense_returns_404(self, alice_client):
        """GET /expenses/99999/edit for a non-existent ID must return 404."""
        response = alice_client.get("/expenses/99999/edit")
        assert (
            response.status_code == 404
        ), f"Expected 404 for non-existent expense, got {response.status_code}"

    def test_post_non_existent_expense_returns_404(self, alice_client):
        """POST /expenses/99999/edit for a non-existent ID must return 404."""
        response = alice_client.post("/expenses/99999/edit", data=VALID_EDIT_FORM)
        assert (
            response.status_code == 404
        ), f"Expected 404 for non-existent expense on POST, got {response.status_code}"


# ===========================================================================
# 3. 403 — OWNERSHIP ENFORCEMENT
# ===========================================================================


class TestOwnershipEnforcement:
    """A user must not be able to GET or POST another user's expense — must return 403."""

    def test_get_other_users_expense_returns_403(self, alice_client, bob_expense):
        """Alice must get 403 when trying to GET an expense that belongs to Bob."""
        response = alice_client.get(f"/expenses/{bob_expense}/edit")
        assert response.status_code == 403, (
            f"Expected 403 when accessing another user's expense via GET, "
            f"got {response.status_code}"
        )

    def test_post_other_users_expense_returns_403(self, alice_client, bob_expense):
        """Alice must get 403 when trying to POST an update to Bob's expense."""
        response = alice_client.post(
            f"/expenses/{bob_expense}/edit", data=VALID_EDIT_FORM
        )
        assert response.status_code == 403, (
            f"Expected 403 when POSTing to another user's expense, "
            f"got {response.status_code}"
        )

    def test_post_other_users_expense_does_not_modify_db(
        self, alice_client, bob_expense, isolated_db
    ):
        """Alice's 403 POST must not mutate Bob's expense row in the DB."""
        _, conn = isolated_db
        original = _fetch_expense(conn, bob_expense)
        alice_client.post(f"/expenses/{bob_expense}/edit", data=VALID_EDIT_FORM)
        after = _fetch_expense(conn, bob_expense)
        assert (
            original["amount"] == after["amount"]
        ), "Cross-user POST must not change the expense amount"
        assert (
            original["category"] == after["category"]
        ), "Cross-user POST must not change the expense category"

    def test_bob_cannot_get_alices_expense(self, bob_client, alice_expense):
        """Bob must get 403 when trying to GET Alice's expense."""
        response = bob_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 403, (
            f"Bob must receive 403 when accessing Alice's expense, "
            f"got {response.status_code}"
        )


# ===========================================================================
# 4. GET HAPPY PATH — FORM RENDERING
# ===========================================================================


class TestGetEditExpenseForm:
    """Authenticated GET for an owned expense must render the form pre-filled from the DB."""

    def test_get_own_expense_returns_200(self, alice_client, alice_expense):
        """Authenticated GET /expenses/<id>/edit for own expense must return 200."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_get_prefills_amount_from_db(self, alice_client, alice_expense):
        """The amount field must be pre-filled with the expense's stored amount."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        # The expense was inserted with amount=50.00; route formats as "%.2f"
        assert (
            b"50.00" in response.data
        ), "Amount field must be pre-filled with the DB value '50.00'"

    def test_get_prefills_category_from_db(self, alice_client, alice_expense):
        """The category field must reflect the expense's stored category."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        assert (
            b"Food" in response.data
        ), "Category 'Food' must appear pre-selected in the form"

    def test_get_prefills_date_from_db(self, alice_client, alice_expense):
        """The date field must be pre-filled with the expense's stored date."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        assert (
            b"2026-05-10" in response.data
        ), "Date field must be pre-filled with the DB value '2026-05-10'"

    def test_get_prefills_description_from_db(self, alice_client, alice_expense):
        """The description field must be pre-filled with the expense's stored description."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        assert (
            b"Original lunch" in response.data
        ), "Description must be pre-filled with the DB value 'Original lunch'"

    def test_get_renders_amount_input_field(self, alice_client, alice_expense):
        """Form must contain an input with name='amount'."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        assert (
            b'name="amount"' in response.data
        ), "Form must render an input with name='amount'"

    def test_get_renders_category_select_field(self, alice_client, alice_expense):
        """Form must contain a select or input with name='category'."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        assert (
            b'name="category"' in response.data
        ), "Form must render a select/input with name='category'"

    def test_get_renders_date_input_field(self, alice_client, alice_expense):
        """Form must contain an input with name='date'."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        assert (
            b'name="date"' in response.data
        ), "Form must render an input with name='date'"

    def test_get_renders_description_input_field(self, alice_client, alice_expense):
        """Form must contain an input with name='description'."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        assert (
            b'name="description"' in response.data
        ), "Form must render an input/textarea with name='description'"

    def test_get_renders_all_valid_categories_in_dropdown(
        self, alice_client, alice_expense
    ):
        """All 7 valid categories must appear as options in the category dropdown."""
        valid_categories = [
            "Food",
            "Transport",
            "Bills",
            "Health",
            "Entertainment",
            "Shopping",
            "Other",
        ]
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        data = response.data.decode()
        for cat in valid_categories:
            assert (
                cat in data
            ), f"Category '{cat}' must appear as an option in the category dropdown"

    def test_get_page_extends_base_template(self, alice_client, alice_expense):
        """Edit expense page must extend base.html — must produce a full HTML document."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        data = response.data.decode()
        assert (
            "<html" in data or "<!DOCTYPE" in data
        ), "Page must extend base.html and produce a full HTML document"


# ===========================================================================
# 5. CANCEL LINK AND TEMPLATE URL USAGE
# ===========================================================================


class TestTemplateLinks:
    """The cancel link and form action must resolve correctly."""

    def test_cancel_link_resolves_to_profile(self, alice_client, alice_expense):
        """The Cancel link must href to /profile (url_for('profile') output)."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        data = response.data.decode()
        assert (
            'href="/profile"' in data or "href='/profile'" in data
        ), "Cancel link must have href='/profile'"

    def test_form_action_resolves_to_edit_expense_route(
        self, alice_client, alice_expense
    ):
        """The form action must resolve to /expenses/<id>/edit."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        data = response.data.decode()
        expected_action = f"/expenses/{alice_expense}/edit"
        assert (
            expected_action in data
        ), f"Form action must resolve to '{expected_action}'"

    def test_no_hardcoded_absolute_urls_in_links(self, alice_client, alice_expense):
        """Template must not contain hardcoded http:// absolute URLs in href attributes."""
        response = alice_client.get(f"/expenses/{alice_expense}/edit")
        assert response.status_code == 200
        data = response.data.decode()
        assert (
            'href="http://' not in data and "href='http://" not in data
        ), "Template must not use hardcoded absolute http:// URLs in href attributes"


# ===========================================================================
# 6. POST HAPPY PATH — VALID SUBMISSION
# ===========================================================================


class TestValidEditSubmission:
    """A valid POST must update the DB row and redirect to /profile."""

    def test_valid_post_redirects_to_profile(self, alice_client, alice_expense):
        """Successful POST must redirect (302) to /profile."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit", data=VALID_EDIT_FORM
        )
        assert (
            response.status_code == 302
        ), f"Expected 302 redirect on success, got {response.status_code}"
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), f"Success redirect must point to /profile, got: {location}"

    def test_valid_post_updates_amount_in_db(
        self, alice_client, alice_expense, isolated_db
    ):
        """After a valid POST, the expense's amount must be updated in the DB."""
        _, conn = isolated_db
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "amount": "123.45"},
        )
        row = _fetch_expense(conn, alice_expense)
        assert (
            abs(row["amount"] - 123.45) < 0.001
        ), f"DB amount must be updated to 123.45, got {row['amount']}"

    def test_valid_post_updates_category_in_db(
        self, alice_client, alice_expense, isolated_db
    ):
        """After a valid POST, the expense's category must be updated in the DB."""
        _, conn = isolated_db
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "category": "Health"},
        )
        row = _fetch_expense(conn, alice_expense)
        assert (
            row["category"] == "Health"
        ), f"DB category must be updated to 'Health', got '{row['category']}'"

    def test_valid_post_updates_date_in_db(
        self, alice_client, alice_expense, isolated_db
    ):
        """After a valid POST, the expense's date must be updated in the DB."""
        _, conn = isolated_db
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "date": "2026-04-01"},
        )
        row = _fetch_expense(conn, alice_expense)
        assert (
            row["date"] == "2026-04-01"
        ), f"DB date must be updated to '2026-04-01', got '{row['date']}'"

    def test_valid_post_updates_description_in_db(
        self, alice_client, alice_expense, isolated_db
    ):
        """After a valid POST, the expense's description must be updated in the DB."""
        _, conn = isolated_db
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "description": "New description text 42"},
        )
        row = _fetch_expense(conn, alice_expense)
        assert (
            row["description"] == "New description text 42"
        ), f"DB description must be updated, got '{row['description']}'"

    def test_valid_post_does_not_create_new_row(
        self, alice_client, alice, alice_expense, isolated_db
    ):
        """A valid edit POST must update the existing row, not insert a new one."""
        user_id, _, _ = alice
        _, conn = isolated_db
        before = _count_expenses(conn, user_id)
        alice_client.post(f"/expenses/{alice_expense}/edit", data=VALID_EDIT_FORM)
        after = _count_expenses(conn, user_id)
        assert (
            after == before
        ), f"Edit must not insert a new row; expense count before={before}, after={after}"

    def test_valid_post_updated_values_visible_on_profile(
        self, alice_client, alice_expense
    ):
        """After a successful edit, the updated description must appear on the profile page."""
        unique_desc = "Edited unique cinema expense for profile check"
        today = date.today().isoformat()
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={
                "amount": "30.00",
                "category": "Entertainment",
                "date": today,
                "description": unique_desc,
            },
        )
        profile_response = alice_client.get("/profile?filter=all_time")
        assert (
            unique_desc.encode() in profile_response.data
        ), f"Updated description '{unique_desc}' must appear on the profile page"

    @pytest.mark.parametrize(
        "category",
        ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"],
    )
    def test_all_valid_categories_accepted_on_edit(
        self, alice_client, alice_expense, isolated_db, category
    ):
        """Each of the 7 valid categories must be accepted and saved on a valid edit."""
        _, conn = isolated_db
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "category": category},
        )
        assert (
            response.status_code == 302
        ), f"Category '{category}' must be accepted on edit; got {response.status_code}"
        row = _fetch_expense(conn, alice_expense)
        assert (
            row["category"] == category
        ), f"Category '{category}' must be persisted in the DB"

    def test_valid_post_with_empty_description_clears_description(
        self, alice_client, alice_expense, isolated_db
    ):
        """Submitting an empty description must be accepted and save NULL/empty in DB."""
        _, conn = isolated_db
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "description": ""},
        )
        assert (
            response.status_code == 302
        ), "Empty description must still result in a successful redirect"
        row = _fetch_expense(conn, alice_expense)
        # description should be None (NULL) or empty string after clearing
        assert (
            row["description"] is None or row["description"] == ""
        ), f"Empty description must be stored as NULL or empty, got '{row['description']}'"


# ===========================================================================
# 7. VALIDATION ERRORS — AMOUNT
# ===========================================================================


class TestAmountValidation:
    """Amount field must reject empty, zero, negative, non-numeric, and over-limit values."""

    @pytest.mark.parametrize("bad_amount", ["", "0", "-1", "-0.01", "abc", "1000001"])
    def test_invalid_amount_returns_200_with_error(
        self, alice_client, alice_expense, bad_amount
    ):
        """All disallowed amounts must return 200 (re-render) instead of a redirect."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "amount": bad_amount},
        )
        assert (
            response.status_code == 200
        ), f"Amount '{bad_amount}' must be rejected; expected 200, got {response.status_code}"

    @pytest.mark.parametrize("bad_amount", ["", "0", "-1", "-0.01", "abc", "1000001"])
    def test_invalid_amount_does_not_update_db(
        self, alice_client, alice_expense, isolated_db, bad_amount
    ):
        """All disallowed amounts must not mutate the DB row."""
        _, conn = isolated_db
        original = _fetch_expense(conn, alice_expense)
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "amount": bad_amount},
        )
        after = _fetch_expense(conn, alice_expense)
        assert original["amount"] == after["amount"], (
            f"Invalid amount '{bad_amount}' must not update DB amount; "
            f"original={original['amount']}, after={after['amount']}"
        )

    def test_amount_at_boundary_one_million_accepted(
        self, alice_client, alice_expense, isolated_db
    ):
        """Amount of exactly 1,000,000 must be accepted (boundary is ≤ 1,000,000)."""
        _, conn = isolated_db
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "amount": "1000000"},
        )
        assert (
            response.status_code == 302
        ), "Amount of exactly 1,000,000 must be accepted and redirect to /profile"
        row = _fetch_expense(conn, alice_expense)
        assert (
            abs(row["amount"] - 1_000_000) < 0.001
        ), f"Amount 1,000,000 must be saved; got {row['amount']}"

    def test_amount_above_one_million_rejected(self, alice_client, alice_expense):
        """Amount exceeding 1,000,000 must be rejected with a 200 error response."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "amount": "1000000.01"},
        )
        assert (
            response.status_code == 200
        ), "Amount above 1,000,000 must be rejected; expected 200 re-render"

    def test_invalid_amount_shows_error_message(self, alice_client, alice_expense):
        """The re-rendered form must include an error message when amount is invalid."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "amount": "0"},
        )
        assert response.status_code == 200
        data = response.data.decode().lower()
        assert (
            "error" in data or "amount" in data or "valid" in data
        ), "A validation error message must appear when an invalid amount is submitted"


# ===========================================================================
# 8. VALIDATION ERRORS — CATEGORY
# ===========================================================================


class TestCategoryValidation:
    """Category must be one of the 7 allowed values — anything else is rejected."""

    @pytest.mark.parametrize(
        "bad_category", ["", "food", "FOOD", "InvalidCategory", "Expenses", "transport"]
    )
    def test_invalid_category_returns_200(
        self, alice_client, alice_expense, bad_category
    ):
        """Unrecognised or wrong-cased categories must return 200 (re-render)."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "category": bad_category},
        )
        assert response.status_code == 200, (
            f"Category '{bad_category}' must be rejected; expected 200, "
            f"got {response.status_code}"
        )

    @pytest.mark.parametrize(
        "bad_category", ["", "food", "FOOD", "InvalidCategory", "Expenses", "transport"]
    )
    def test_invalid_category_does_not_update_db(
        self, alice_client, alice_expense, isolated_db, bad_category
    ):
        """Unrecognised categories must not mutate the DB row."""
        _, conn = isolated_db
        original = _fetch_expense(conn, alice_expense)
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "category": bad_category},
        )
        after = _fetch_expense(conn, alice_expense)
        assert (
            original["category"] == after["category"]
        ), f"Invalid category '{bad_category}' must not update DB category"


# ===========================================================================
# 9. VALIDATION ERRORS — DATE
# ===========================================================================


class TestDateValidation:
    """Date must be a valid ISO format and must not be in the future."""

    def test_future_date_returns_200_with_error(self, alice_client, alice_expense):
        """A date set to tomorrow must be rejected with a 200 error response."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "date": tomorrow},
        )
        assert (
            response.status_code == 200
        ), f"Future date must be rejected; expected 200, got {response.status_code}"

    def test_future_date_does_not_update_db(
        self, alice_client, alice_expense, isolated_db
    ):
        """A future date submission must not update the DB row."""
        _, conn = isolated_db
        original = _fetch_expense(conn, alice_expense)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "date": tomorrow},
        )
        after = _fetch_expense(conn, alice_expense)
        assert (
            original["date"] == after["date"]
        ), "Future date submission must not update the expense date in DB"

    def test_today_date_is_accepted(self, alice_client, alice_expense, isolated_db):
        """Today's date must be accepted as a valid (non-future) date."""
        _, conn = isolated_db
        today = date.today().isoformat()
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "date": today},
        )
        assert (
            response.status_code == 302
        ), f"Today's date must be accepted; expected 302, got {response.status_code}"

    @pytest.mark.parametrize(
        "bad_date", ["not-a-date", "32-13-2026", "2026/06/01", "June 1", "01/05/2026"]
    )
    def test_malformed_date_returns_200(self, alice_client, alice_expense, bad_date):
        """Non-ISO and malformed date strings must be rejected with a 200 error response."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "date": bad_date},
        )
        assert (
            response.status_code == 200
        ), f"Date '{bad_date}' must be rejected; expected 200, got {response.status_code}"

    @pytest.mark.parametrize(
        "bad_date", ["not-a-date", "32-13-2026", "2026/06/01", "June 1", "01/05/2026"]
    )
    def test_malformed_date_does_not_update_db(
        self, alice_client, alice_expense, isolated_db, bad_date
    ):
        """Malformed date strings must not mutate the DB row."""
        _, conn = isolated_db
        original = _fetch_expense(conn, alice_expense)
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "date": bad_date},
        )
        after = _fetch_expense(conn, alice_expense)
        assert (
            original["date"] == after["date"]
        ), f"Malformed date '{bad_date}' must not update the expense date in DB"

    def test_far_future_date_rejected(self, alice_client, alice_expense):
        """A date years in the future must also be rejected."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "date": "2099-12-31"},
        )
        assert (
            response.status_code == 200
        ), "A far-future date must be rejected with 200 re-render"


# ===========================================================================
# 10. VALIDATION ERRORS — DESCRIPTION
# ===========================================================================


class TestDescriptionValidation:
    """Description must be 200 characters or fewer."""

    def test_description_over_200_chars_returns_200_with_error(
        self, alice_client, alice_expense
    ):
        """A description longer than 200 characters must return 200 (re-render)."""
        long_desc = "x" * 201
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "description": long_desc},
        )
        assert response.status_code == 200, (
            f"Description > 200 chars must be rejected; expected 200, "
            f"got {response.status_code}"
        )

    def test_description_over_200_chars_does_not_update_db(
        self, alice_client, alice_expense, isolated_db
    ):
        """A too-long description must not update the DB row."""
        _, conn = isolated_db
        original = _fetch_expense(conn, alice_expense)
        long_desc = "y" * 201
        alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "description": long_desc},
        )
        after = _fetch_expense(conn, alice_expense)
        assert (
            original["description"] == after["description"]
        ), "Description > 200 chars must not update the expense description in DB"

    def test_description_exactly_200_chars_is_accepted(
        self, alice_client, alice_expense, isolated_db
    ):
        """A description of exactly 200 characters must be accepted."""
        _, conn = isolated_db
        exact_desc = "a" * 200
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "description": exact_desc},
        )
        assert (
            response.status_code == 302
        ), "Description of exactly 200 chars must be accepted (boundary is inclusive)"
        row = _fetch_expense(conn, alice_expense)
        assert (
            row["description"] == exact_desc
        ), "200-char description must be saved exactly as submitted"

    def test_description_over_200_chars_shows_error_message(
        self, alice_client, alice_expense
    ):
        """The re-rendered form must include an error message for an over-long description."""
        long_desc = "z" * 201
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "description": long_desc},
        )
        assert response.status_code == 200
        data = response.data.decode().lower()
        assert (
            "error" in data or "200" in data or "description" in data
        ), "A validation error must appear when description exceeds 200 characters"


# ===========================================================================
# 11. FORM VALUE RETENTION ON VALIDATION FAILURE
# ===========================================================================


class TestFormRetainsSubmittedValues:
    """
    After a failed POST, the form must echo back the submitted values
    (not the original DB values) so the user can correct their input.
    """

    def test_submitted_amount_retained_after_invalid_category(
        self, alice_client, alice_expense
    ):
        """After a category validation failure, the submitted amount must be visible."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={
                "amount": "777.77",
                "category": "BadCategory",
                "date": "2026-05-01",
                "description": "Retention test",
            },
        )
        assert response.status_code == 200
        assert (
            b"777.77" in response.data
        ), "Submitted amount '777.77' must be retained in the re-rendered form"

    def test_submitted_description_retained_after_invalid_amount(
        self, alice_client, alice_expense
    ):
        """After an amount validation failure, the submitted description must be visible."""
        unique_desc = "Retention unique desc 5678"
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={
                "amount": "0",
                "category": "Food",
                "date": "2026-05-01",
                "description": unique_desc,
            },
        )
        assert response.status_code == 200
        assert (
            unique_desc.encode() in response.data
        ), "Submitted description must be retained after a failed amount validation"

    def test_submitted_category_retained_after_invalid_amount(
        self, alice_client, alice_expense
    ):
        """After an amount validation failure, the submitted category must appear."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={
                "amount": "-5",
                "category": "Bills",
                "date": "2026-05-01",
                "description": "",
            },
        )
        assert response.status_code == 200
        data = response.data.decode()
        assert (
            "Bills" in data
        ), "Submitted category 'Bills' must appear in the re-rendered form after failure"

    def test_submitted_date_retained_after_invalid_category(
        self, alice_client, alice_expense
    ):
        """After a category validation failure, the submitted date must be visible."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={
                "amount": "50.00",
                "category": "BadCategory",
                "date": "2026-03-25",
                "description": "",
            },
        )
        assert response.status_code == 200
        assert (
            b"2026-03-25" in response.data
        ), "Submitted date '2026-03-25' must be retained in the re-rendered form"

    def test_submitted_values_override_original_db_values_on_failure(
        self, alice_client, alice_expense
    ):
        """
        When validation fails, the form must show the NEW submitted values,
        not the original values that were in the DB before the edit attempt.
        The fixture inserts amount=50.00; we submit 999.99 with a bad category.
        The re-rendered form must show 999.99 (submitted), not 50.00 (DB original).
        """
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={
                "amount": "999.99",
                "category": "BadCategory",
                "date": "2026-05-01",
                "description": "Overriding value test",
            },
        )
        assert response.status_code == 200
        assert b"999.99" in response.data, (
            "The submitted amount '999.99' must appear in the re-rendered form, "
            "not the original DB value '50.00'"
        )

    def test_error_message_displayed_on_any_validation_failure(
        self, alice_client, alice_expense
    ):
        """A visible error message must be present after any validation failure."""
        response = alice_client.post(
            f"/expenses/{alice_expense}/edit",
            data={**VALID_EDIT_FORM, "amount": "-99"},
        )
        assert response.status_code == 200
        data = response.data.decode().lower()
        assert (
            "error" in data
            or "invalid" in data
            or "positive" in data
            or "valid" in data
        ), "A validation error message must appear on the re-rendered form page"


# ===========================================================================
# 12. EDIT LINK ON PROFILE PAGE
# ===========================================================================


class TestEditLinkOnProfile:
    """The profile page must render an Edit link for each expense row."""

    def test_edit_link_present_on_profile_for_own_expense(
        self, alice_client, alice, alice_expense, isolated_db
    ):
        """An Edit link pointing to /expenses/<id>/edit must appear on the profile page."""
        response = alice_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        data = response.data.decode()
        expected_href = f"/expenses/{alice_expense}/edit"
        assert (
            expected_href in data
        ), f"Edit link '{expected_href}' must appear on the profile page"

    def test_edit_link_for_multiple_expenses(self, alice_client, alice, isolated_db):
        """Edit links must appear for each expense row, not just the first one."""
        user_id, _, _ = alice
        _, conn = isolated_db
        exp1 = _insert_expense(
            conn, user_id, 10.00, "Food", "2026-04-01", "Expense one"
        )
        exp2 = _insert_expense(
            conn, user_id, 20.00, "Bills", "2026-04-02", "Expense two"
        )

        response = alice_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        data = response.data.decode()
        assert (
            f"/expenses/{exp1}/edit" in data
        ), f"Edit link for expense {exp1} must be present on profile page"
        assert (
            f"/expenses/{exp2}/edit" in data
        ), f"Edit link for expense {exp2} must be present on profile page"

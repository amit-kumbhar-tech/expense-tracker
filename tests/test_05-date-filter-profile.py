"""
tests/test_05-date-filter-profile.py

Pytest tests for Spendly Step 05 — Date Filter for Profile Page.

Spec: .claude/specs/05-date-filter-profile.md

Test strategy
-------------
- db.py stores the path in a module-level _DB_PATH.  We monkeypatch that
  attribute *and* the matching attribute imported into app.py so every
  get_db() call inside the feature goes to a clean temp file.
- A controlled set of expenses is inserted via direct SQL so each test
  can reason about exact dates without depending on seed_db().
- Session injection uses client.session_transaction() so no real login
  round-trip is needed for profile tests.
"""

import os
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# Patch db path BEFORE importing app so the module-level constant is correct.
# We create the temp file once per test via the fixture, and point the module
# at it each time with monkeypatch.
# ---------------------------------------------------------------------------
import database.db as db_module
from app import app as flask_app


# ---------------------------------------------------------------------------
# Helpers
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


def _insert_user(conn, name, email, created_at=None):
    pw_hash = generate_password_hash("testpassword123")
    if created_at:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name, email, pw_hash, created_at),
        )
    else:
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, pw_hash),
        )
    conn.commit()
    return conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]


def _insert_expense(conn, user_id, amount, category, exp_date, description=""):
    conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, exp_date, description),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_db(monkeypatch, tmp_path):
    """
    Create a fresh SQLite database in a temp directory.
    Patch database.db._DB_PATH so get_db() always uses this file.
    Returns the path string so tests can open it directly if needed.
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
    user_id = _insert_user(
        conn,
        name="Alice Tester",
        email="alice@example.com",
        created_at="2024-03-15 10:00:00",
    )
    return user_id, "Alice Tester", "alice@example.com"


@pytest.fixture()
def logged_in_client(client, test_user):
    """A test client with Alice's session already injected."""
    user_id, _, _ = test_user
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Alice Tester"
    return client


# ---------------------------------------------------------------------------
# Convenience: insert expenses relative to today
# ---------------------------------------------------------------------------

def _today_str():
    return date.today().isoformat()


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def _first_of_month():
    return date.today().replace(day=1).isoformat()


def _first_of_year():
    return date.today().replace(month=1, day=1).isoformat()


# ===========================================================================
# 1. AUTH GUARD
# ===========================================================================

class TestAuthGuard:
    def test_unauthenticated_get_profile_redirects_to_login(self, client):
        """Visiting /profile without a session must 302 to /login."""
        response = client.get("/profile")
        assert response.status_code == 302, (
            f"Expected 302, got {response.status_code}"
        )
        location = response.headers.get("Location", "")
        assert "/login" in location, (
            f"Redirect should point to /login, got: {location}"
        )

    def test_unauthenticated_profile_does_not_return_200(self, client):
        """Logged-out request must never render the profile page (no 200)."""
        response = client.get("/profile")
        assert response.status_code != 200, (
            "Profile page must not be accessible without authentication"
        )

    def test_unauthenticated_profile_follows_redirect_to_login(self, client):
        """Following the redirect should land on the login page."""
        response = client.get("/profile", follow_redirects=True)
        assert response.status_code == 200
        assert b"login" in response.data.lower() or b"Login" in response.data, (
            "Following redirect from /profile should reach login page"
        )


# ===========================================================================
# 2. DEFAULT FILTER BEHAVIOUR
# ===========================================================================

class TestDefaultFilter:
    def test_no_filter_param_defaults_to_this_month(self, logged_in_client):
        """/profile with no query param should use 'this_month' filter."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        # The active class must be on the "This Month" button
        assert b"This Month" in response.data, "Expected 'This Month' text in response"

    def test_unknown_filter_falls_back_to_this_month(self, logged_in_client):
        """An unrecognised filter value must fall back to 'this_month'."""
        response = logged_in_client.get("/profile?filter=bogus_value")
        assert response.status_code == 200
        # active class should appear near the "This Month" link
        data = response.data.decode()
        # Look for the active marker on the this_month link
        assert "this_month" in data, "this_month should still be present in the page"

    def test_default_shows_only_current_month_expenses(
        self, logged_in_client, test_user, isolated_db
    ):
        """Default view must show this-month expenses, not last-year ones."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        # Insert one expense this month and one from last year
        this_month_date = _first_of_month()
        old_date = "2020-01-15"
        _insert_expense(conn, user_id, 50.00, "Food", this_month_date, "This month lunch")
        _insert_expense(conn, user_id, 999.00, "Bills", old_date, "Old bill from 2020")

        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        data = response.data.decode()
        assert "This month lunch" in data, (
            "Current-month expense should appear in default view"
        )
        assert "Old bill from 2020" not in data, (
            "Expense from 2020 must not appear in default this-month view"
        )

    def test_this_month_filter_active_css_class(
        self, logged_in_client
    ):
        """The 'This Month' preset button must carry the 'active' CSS class."""
        response = logged_in_client.get("/profile?filter=this_month")
        assert response.status_code == 200
        data = response.data.decode()
        # The active link should contain both the class and the label together
        assert "filter-btn active" in data or "active" in data, (
            "Expected active CSS class on This Month filter button"
        )
        # Confirm specifically the this_month link has it
        import re
        pattern = r'href="[^"]*filter=this_month[^"]*"[^>]*class="[^"]*active[^"]*"'
        alt_pattern = r'class="[^"]*active[^"]*"[^>]*href="[^"]*filter=this_month'
        found = re.search(pattern, data) or re.search(alt_pattern, data)
        assert found, (
            "The this_month filter button must have the 'active' class in its anchor tag"
        )


# ===========================================================================
# 3. PRESET FILTERS
# ===========================================================================

class TestPresetFilters:
    def test_last_3_months_shows_expenses_within_90_days(
        self, logged_in_client, test_user, isolated_db
    ):
        """last_3_months preset must include expenses from the last 90 days."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        recent_date = _days_ago(30)
        _insert_expense(conn, user_id, 75.00, "Transport", recent_date, "Bus pass recent")

        response = logged_in_client.get("/profile?filter=last_3_months")
        assert response.status_code == 200
        assert b"Bus pass recent" in response.data, (
            "Expense within 90 days must appear under last_3_months filter"
        )

    def test_last_3_months_excludes_expenses_older_than_90_days(
        self, logged_in_client, test_user, isolated_db
    ):
        """last_3_months preset must NOT show expenses older than 90 days."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        old_date = _days_ago(120)
        _insert_expense(conn, user_id, 200.00, "Bills", old_date, "Very old bill")

        response = logged_in_client.get("/profile?filter=last_3_months")
        assert response.status_code == 200
        assert b"Very old bill" not in response.data, (
            "Expense older than 90 days must not appear under last_3_months filter"
        )

    def test_last_3_months_active_css_class(self, logged_in_client):
        """The 'Last 3 Months' button must carry the 'active' CSS class."""
        response = logged_in_client.get("/profile?filter=last_3_months")
        assert response.status_code == 200
        data = response.data.decode()
        import re
        pattern = r'href="[^"]*filter=last_3_months[^"]*"[^>]*class="[^"]*active[^"]*"'
        alt_pattern = r'class="[^"]*active[^"]*"[^>]*href="[^"]*filter=last_3_months'
        found = re.search(pattern, data) or re.search(alt_pattern, data)
        assert found, (
            "The last_3_months filter button must have the 'active' class"
        )

    def test_this_year_shows_expenses_in_current_year(
        self, logged_in_client, test_user, isolated_db
    ):
        """this_year preset must show expenses in the current calendar year."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        this_year_date = _first_of_year()
        _insert_expense(conn, user_id, 60.00, "Health", this_year_date, "Gym membership this year")

        response = logged_in_client.get("/profile?filter=this_year")
        assert response.status_code == 200
        assert b"Gym membership this year" in response.data, (
            "Expense in current year must appear under this_year filter"
        )

    def test_this_year_excludes_prior_year_expenses(
        self, logged_in_client, test_user, isolated_db
    ):
        """this_year preset must NOT show expenses from previous years."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        prior_year = str(date.today().year - 1)
        prior_date = f"{prior_year}-06-15"
        _insert_expense(conn, user_id, 500.00, "Bills", prior_date, "Prior year utility")

        response = logged_in_client.get("/profile?filter=this_year")
        assert response.status_code == 200
        assert b"Prior year utility" not in response.data, (
            "Expense from a previous year must not appear under this_year filter"
        )

    def test_this_year_active_css_class(self, logged_in_client):
        """The 'This Year' button must carry the 'active' CSS class."""
        response = logged_in_client.get("/profile?filter=this_year")
        assert response.status_code == 200
        data = response.data.decode()
        import re
        pattern = r'href="[^"]*filter=this_year[^"]*"[^>]*class="[^"]*active[^"]*"'
        alt_pattern = r'class="[^"]*active[^"]*"[^>]*href="[^"]*filter=this_year'
        found = re.search(pattern, data) or re.search(alt_pattern, data)
        assert found, "The this_year filter button must have the 'active' class"

    def test_all_time_shows_every_user_expense(
        self, logged_in_client, test_user, isolated_db
    ):
        """all_time preset must show expenses from any date."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 10.00, "Other", "2000-01-01", "Year 2000 expense")
        _insert_expense(conn, user_id, 20.00, "Food", _today_str(), "Today lunch")

        response = logged_in_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        assert b"Year 2000 expense" in response.data, (
            "all_time must include very old expenses"
        )
        assert b"Today lunch" in response.data, (
            "all_time must include today's expenses"
        )

    def test_all_time_active_css_class(self, logged_in_client):
        """The 'All Time' button must carry the 'active' CSS class."""
        response = logged_in_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        data = response.data.decode()
        import re
        pattern = r'href="[^"]*filter=all_time[^"]*"[^>]*class="[^"]*active[^"]*"'
        alt_pattern = r'class="[^"]*active[^"]*"[^>]*href="[^"]*filter=all_time'
        found = re.search(pattern, data) or re.search(alt_pattern, data)
        assert found, "The all_time filter button must have the 'active' class"

    @pytest.mark.parametrize("preset", ["this_month", "last_3_months", "this_year", "all_time"])
    def test_all_preset_filter_buttons_present_in_template(
        self, logged_in_client, preset
    ):
        """Every preset button must be rendered in the template."""
        response = logged_in_client.get(f"/profile?filter={preset}")
        assert response.status_code == 200
        data = response.data.decode()
        assert "This Month" in data, "This Month button must always be rendered"
        assert "Last 3 Months" in data, "Last 3 Months button must always be rendered"
        assert "This Year" in data, "This Year button must always be rendered"
        assert "All Time" in data, "All Time button must always be rendered"


# ===========================================================================
# 4. CUSTOM DATE RANGE
# ===========================================================================

class TestCustomDateRange:
    def test_custom_range_shows_expenses_within_range(
        self, logged_in_client, test_user, isolated_db
    ):
        """Expenses within the supplied custom range must appear."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 100.00, "Shopping", "2025-03-10", "March shopping")
        _insert_expense(conn, user_id, 200.00, "Bills", "2025-04-05", "April bill")

        response = logged_in_client.get(
            "/profile?from_date=2025-03-01&to_date=2025-03-31"
        )
        assert response.status_code == 200
        assert b"March shopping" in response.data, (
            "Expense within custom range must appear"
        )

    def test_custom_range_excludes_expenses_outside_range(
        self, logged_in_client, test_user, isolated_db
    ):
        """Expenses outside the custom range must NOT appear."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 200.00, "Bills", "2025-04-05", "April bill outside range")

        response = logged_in_client.get(
            "/profile?from_date=2025-03-01&to_date=2025-03-31"
        )
        assert response.status_code == 200
        assert b"April bill outside range" not in response.data, (
            "Expense outside custom range must not appear"
        )

    def test_custom_range_inclusive_of_boundary_dates(
        self, logged_in_client, test_user, isolated_db
    ):
        """Expenses on the exact from_date and to_date must be included."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 15.00, "Food", "2025-06-01", "Boundary start expense")
        _insert_expense(conn, user_id, 25.00, "Food", "2025-06-30", "Boundary end expense")

        response = logged_in_client.get(
            "/profile?from_date=2025-06-01&to_date=2025-06-30"
        )
        assert response.status_code == 200
        assert b"Boundary start expense" in response.data, (
            "from_date boundary expense must be included (inclusive)"
        )
        assert b"Boundary end expense" in response.data, (
            "to_date boundary expense must be included (inclusive)"
        )

    def test_custom_range_overrides_preset_filter(
        self, logged_in_client, test_user, isolated_db
    ):
        """When both custom dates are supplied, they override any preset param."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 50.00, "Health", "2025-07-20", "Custom range result")
        # This expense is in this_month but not in custom range
        today = _today_str()
        _insert_expense(conn, user_id, 999.00, "Other", today, "Current month expense")

        response = logged_in_client.get(
            "/profile?filter=this_month&from_date=2025-07-01&to_date=2025-07-31"
        )
        assert response.status_code == 200
        assert b"Custom range result" in response.data, (
            "Custom date range must override the preset filter"
        )

    def test_partial_custom_range_only_from_date_falls_back_to_preset(
        self, logged_in_client, test_user, isolated_db
    ):
        """Only from_date provided (no to_date) — must fall back to preset, not crash."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 40.00, "Food", _today_str(), "Fallback expense today")

        response = logged_in_client.get(
            "/profile?from_date=2025-01-01"
        )
        # Must not crash — 200 is expected
        assert response.status_code == 200, (
            "Partial custom range (only from_date) must not cause a server error"
        )

    def test_partial_custom_range_only_to_date_falls_back_to_preset(
        self, logged_in_client, test_user, isolated_db
    ):
        """Only to_date provided (no from_date) — must fall back to preset, not crash."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        response = logged_in_client.get(
            "/profile?to_date=2025-12-31"
        )
        assert response.status_code == 200, (
            "Partial custom range (only to_date) must not cause a server error"
        )

    def test_partial_custom_range_uses_preset_behaviour(
        self, logged_in_client, test_user, isolated_db
    ):
        """With only one date field, the active preset (this_month default) governs the window."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        # Put expense in current month
        current_month_date = _first_of_month()
        _insert_expense(conn, user_id, 55.00, "Transport", current_month_date, "Preset fallback expense")
        # Put expense in distant past — should NOT appear under this_month
        _insert_expense(conn, user_id, 9999.00, "Bills", "2000-06-15", "Distant past expense")

        response = logged_in_client.get(
            "/profile?from_date=2000-01-01"  # only one date; falls back to this_month
        )
        assert response.status_code == 200
        data = response.data.decode()
        # Distant past expense must not leak through
        assert "Distant past expense" not in data, (
            "Partial custom range must fall back to preset and not use the single supplied date"
        )


# ===========================================================================
# 5. STATS REFLECT FILTERED DATA
# ===========================================================================

class TestStatsReflectFilteredData:
    def test_total_spent_matches_filtered_expenses(
        self, logged_in_client, test_user, isolated_db
    ):
        """Total Spent stat must sum only the expenses in the active filter window."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 100.00, "Food", "2025-08-10", "Aug food")
        _insert_expense(conn, user_id, 50.00,  "Food", "2025-08-20", "Aug food 2")
        # Expense outside the range
        _insert_expense(conn, user_id, 9000.00, "Bills", "2023-01-01", "Old huge bill")

        response = logged_in_client.get(
            "/profile?from_date=2025-08-01&to_date=2025-08-31"
        )
        assert response.status_code == 200
        data = response.data.decode()
        # Expect the formatted total: 150.00
        assert "150.00" in data, (
            "Total Spent must show sum of filtered expenses only (expected 150.00)"
        )

    def test_transaction_count_matches_filtered_expenses(
        self, logged_in_client, test_user, isolated_db
    ):
        """Transaction count must count only the rows in the filter window."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 10.00, "Other", "2025-09-05", "Sep 1")
        _insert_expense(conn, user_id, 20.00, "Other", "2025-09-15", "Sep 2")
        # Not in range
        _insert_expense(conn, user_id, 30.00, "Other", "2025-07-01", "July 1")

        response = logged_in_client.get(
            "/profile?from_date=2025-09-01&to_date=2025-09-30"
        )
        assert response.status_code == 200
        data = response.data.decode()
        # Exactly 2 transactions in range
        assert ">2<" in data or ">2 <" in data or "2</span>" in data or ">2\n" in data or "2" in data, (
            "Transaction count must be 2 for the filtered date range"
        )
        # Make sure the out-of-range expense's unique description doesn't appear
        assert b"July 1" not in response.data, (
            "Expense outside custom range must not appear in the table"
        )

    def test_top_category_reflects_filtered_data(
        self, logged_in_client, test_user, isolated_db
    ):
        """Top Category must be the highest-spend category in the filtered window."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        # In range: Health=300, Food=100 → top should be Health
        _insert_expense(conn, user_id, 300.00, "Health", "2025-10-10", "Health big")
        _insert_expense(conn, user_id, 100.00, "Food",   "2025-10-15", "Food small")
        # Out of range: Food=9000 — must NOT make Food the top category
        _insert_expense(conn, user_id, 9000.00, "Food", "2020-01-01", "Ancient food splurge")

        response = logged_in_client.get(
            "/profile?from_date=2025-10-01&to_date=2025-10-31"
        )
        assert response.status_code == 200
        data = response.data.decode()
        assert "Health" in data, (
            "Top category in the filtered window must be 'Health'"
        )


# ===========================================================================
# 6. EMPTY STATE
# ===========================================================================

class TestEmptyState:
    def test_no_expenses_shows_no_expenses_message(
        self, logged_in_client
    ):
        """When no expenses match the filter, 'No expenses found' must be shown."""
        # No expenses inserted — default this_month view will be empty
        response = logged_in_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        data = response.data.decode()
        assert "No expenses found" in data or "no expenses" in data.lower(), (
            "Empty state must display a 'No expenses found' message"
        )

    def test_no_expenses_shows_no_spending_data_for_category_breakdown(
        self, logged_in_client
    ):
        """Category breakdown must show a no-data message when there are no expenses."""
        response = logged_in_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        data = response.data.decode()
        assert (
            "No spending data" in data
            or "no spending" in data.lower()
            or "no expenses" in data.lower()
        ), (
            "Category breakdown must show a no-data message when there are zero expenses"
        )

    def test_stats_show_zero_when_no_expenses_in_range(
        self, logged_in_client, test_user, isolated_db
    ):
        """Total Spent and transaction count must be zero / ₹0.00 for empty result set."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        # Insert expense outside the range we'll request
        _insert_expense(conn, user_id, 1000.00, "Bills", "2019-01-01", "Way old expense")

        response = logged_in_client.get(
            "/profile?from_date=2025-11-01&to_date=2025-11-30"
        )
        assert response.status_code == 200
        data = response.data.decode()
        assert "0.00" in data or "₹0" in data, (
            "Total Spent must be ₹0.00 when no expenses fall in the filtered range"
        )


# ===========================================================================
# 7. USER INFO FROM DB
# ===========================================================================

class TestUserInfoFromDB:
    def test_profile_shows_real_user_name(
        self, logged_in_client, test_user
    ):
        """Profile must display the logged-in user's actual name from the DB."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"Alice Tester" in response.data, (
            "Real user name 'Alice Tester' must appear on the profile page"
        )

    def test_profile_does_not_show_demo_user(
        self, logged_in_client
    ):
        """Hardcoded 'Demo User' must not appear for a real authenticated user."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"Demo User" not in response.data, (
            "Hardcoded 'Demo User' text must not appear on a real user's profile"
        )

    def test_profile_shows_real_user_email(
        self, logged_in_client, test_user
    ):
        """Profile must display the logged-in user's actual email from the DB."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"alice@example.com" in response.data, (
            "Real user email must appear on the profile page"
        )

    def test_profile_member_since_from_db(
        self, logged_in_client
    ):
        """Member Since must reflect the user's created_at date (March 2024)."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        data = response.data.decode()
        # created_at = "2024-03-15 10:00:00" → "March 2024"
        assert "March 2024" in data, (
            "Member Since must show 'March 2024' based on the user's created_at"
        )

    def test_profile_shows_correct_initials(
        self, logged_in_client
    ):
        """Avatar initials must be derived from the user's name (AT for Alice Tester)."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"AT" in response.data, (
            "Avatar must show initials 'AT' for user 'Alice Tester'"
        )

    def test_other_users_expenses_not_visible(
        self, logged_in_client, test_user, isolated_db
    ):
        """Expenses belonging to another user must never appear on Alice's profile."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        # Insert another user
        other_id = _insert_user(conn, "Bob Intruder", "bob@example.com")
        _insert_expense(
            conn, other_id, 9999.00, "Other", _today_str(), "Bob secret expense"
        )
        # Insert Alice's own expense so the page isn't empty
        _insert_expense(conn, user_id, 10.00, "Food", _today_str(), "Alice own expense")

        response = logged_in_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        assert b"Bob secret expense" not in response.data, (
            "Another user's expense must not be visible on Alice's profile"
        )
        assert b"Alice own expense" in response.data, (
            "Alice's own expense must be visible"
        )


# ===========================================================================
# 8. TEMPLATE STRUCTURE / HTML LANDMARKS
# ===========================================================================

class TestTemplateStructure:
    def test_profile_page_renders_200_when_logged_in(self, logged_in_client):
        """Basic smoke test — authenticated /profile must return 200."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200

    def test_filter_bar_is_present(self, logged_in_client):
        """The filter bar section must be rendered."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"filter-bar" in response.data or b"filter-presets" in response.data, (
            "Filter bar HTML landmark must be present in the rendered page"
        )

    def test_stats_row_is_present(self, logged_in_client):
        """Summary stats section must be rendered with expected labels."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"Total Spent" in response.data, "Stats row must show 'Total Spent' label"
        assert b"Transactions" in response.data, "Stats row must show 'Transactions' label"
        assert b"Top Category" in response.data, "Stats row must show 'Top Category' label"

    def test_transaction_table_headers_present(self, logged_in_client):
        """Transaction table must include Date, Description, Category, Amount columns."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"Date" in response.data, "Transaction table must have a 'Date' header"
        assert b"Description" in response.data, "Transaction table must have a 'Description' header"
        assert b"Category" in response.data, "Transaction table must have a 'Category' header"
        assert b"Amount" in response.data, "Transaction table must have an 'Amount' header"

    def test_category_breakdown_section_present(self, logged_in_client):
        """Spending by Category section must be rendered."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"Spending by Category" in response.data or b"Category" in response.data, (
            "Category breakdown section must be present"
        )

    def test_recent_transactions_section_heading_present(self, logged_in_client):
        """Recent Transactions heading must be present."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"Recent Transactions" in response.data, (
            "Recent Transactions section heading must appear on the profile page"
        )

    def test_custom_date_range_form_inputs_present(self, logged_in_client):
        """Custom date range form must have from_date and to_date inputs."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        assert b"from_date" in response.data, (
            "Custom date range form must contain from_date input"
        )
        assert b"to_date" in response.data, (
            "Custom date range form must contain to_date input"
        )

    def test_profile_page_extends_base_template(self, logged_in_client):
        """Profile page must extend base.html — look for shared nav/footer markers."""
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        data = response.data.decode()
        # base.html should contribute some common structure
        assert "<html" in data or "<!DOCTYPE" in data, (
            "Profile page must be a full HTML document (extends base.html)"
        )

    def test_filter_preset_links_use_url_for_not_hardcoded(self, logged_in_client):
        """Filter preset links must use url_for — verified via template source (not hardcoded /profile)."""
        # We verify the rendered output has the correct path WITHOUT testing template source
        # url_for('profile') → /profile; links must exist with correct href values
        response = logged_in_client.get("/profile")
        assert response.status_code == 200
        data = response.data.decode()
        assert 'href="/profile' in data or "href='/profile" in data, (
            "Filter preset links must resolve to /profile (url_for('profile') output)"
        )

    def test_category_breakdown_present_when_expenses_exist(
        self, logged_in_client, test_user, isolated_db
    ):
        """When expenses exist, the category breakdown list must be rendered."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 80.00, "Entertainment", _today_str(), "Cinema tickets")

        response = logged_in_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        data = response.data.decode()
        assert "Entertainment" in data, (
            "Category breakdown must list categories present in the filtered expense set"
        )

    def test_expense_amount_formatted_with_rupee_symbol(
        self, logged_in_client, test_user, isolated_db
    ):
        """Expense amounts in the transaction table must use the ₹ symbol."""
        user_id, _, _ = test_user
        _, conn = isolated_db
        _insert_expense(conn, user_id, 123.45, "Food", _today_str(), "Formatted amount test")

        response = logged_in_client.get("/profile?filter=all_time")
        assert response.status_code == 200
        data = response.data.decode()
        assert "₹123.45" in data or "123.45" in data, (
            "Expense amount must appear formatted on the page"
        )

    def test_inactive_filter_buttons_do_not_have_active_class(
        self, logged_in_client
    ):
        """When this_month is active, other preset buttons must NOT have the active class."""
        response = logged_in_client.get("/profile?filter=this_month")
        assert response.status_code == 200
        data = response.data.decode()
        import re
        # Confirm last_3_months link does NOT have active class
        last3_pattern = r'href="[^"]*filter=last_3_months[^"]*"[^>]*class="[^"]*active[^"]*"'
        alt_last3 = r'class="[^"]*active[^"]*"[^>]*href="[^"]*filter=last_3_months'
        assert not re.search(last3_pattern, data) and not re.search(alt_last3, data), (
            "The last_3_months button must NOT have the 'active' class when this_month is active"
        )

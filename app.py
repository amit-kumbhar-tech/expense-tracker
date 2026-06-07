import os
import sqlite3
from datetime import date, timedelta

from flask import Flask, render_template, request, session, redirect, url_for, abort
from werkzeug.security import generate_password_hash, check_password_hash

from database.db import (
    get_db, init_db, seed_db,
    get_user_by_email, get_user_by_id, create_user,
    get_expenses_for_user, get_expense_stats, get_category_breakdown,
    create_expense,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

_VALID_FILTER_PRESETS = {"this_month", "last_3_months", "this_year", "all_time"}
_VALID_CATEGORIES = {"Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"}


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name     = request.form.get("name", "").strip()
    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name:
        return render_template("register.html", error="Name is required.")

    if len(password) < 8:
        return render_template("register.html",
                               error="Password must be at least 8 characters.")

    if get_user_by_email(email):
        return render_template("register.html",
                               error="An account with that email already exists.")

    pw_hash = generate_password_hash(password)
    try:
        user_id = create_user(name, email, pw_hash)
    except sqlite3.IntegrityError:
        return render_template("register.html",
                               error="An account with that email already exists.")

    session.clear()
    session["user_id"]   = user_id
    session["user_name"] = name
    return redirect(url_for("profile"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    error    = "Invalid email or password."

    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error=error)

    session.clear()
    session["user_id"]   = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    active_filter = request.args.get("filter", "this_month")
    if active_filter not in _VALID_FILTER_PRESETS:
        active_filter = "this_month"

    raw_from = request.args.get("from_date", "").strip()
    raw_to   = request.args.get("to_date",   "").strip()
    use_custom = False
    if raw_from and raw_to:
        try:
            date.fromisoformat(raw_from)
            date.fromisoformat(raw_to)
            use_custom = True
        except ValueError:
            pass  # invalid format — fall through to preset

    today = date.today()
    if use_custom:
        from_date, to_date = raw_from, raw_to
    elif active_filter == "this_month":
        from_date = today.replace(day=1).isoformat()
        to_date   = today.isoformat()
    elif active_filter == "last_3_months":
        from_date = (today - timedelta(days=90)).isoformat()
        to_date   = today.isoformat()
    elif active_filter == "this_year":
        from_date = today.replace(month=1, day=1).isoformat()
        to_date   = today.isoformat()
    else:  # all_time
        from_date = "1900-01-01"
        to_date   = today.isoformat()

    db_user = get_user_by_id(user_id)
    if not db_user:
        return redirect(url_for("login"))

    expenses        = get_expenses_for_user(user_id, from_date, to_date)
    stats           = get_expense_stats(user_id, from_date, to_date)
    raw_categories  = get_category_breakdown(user_id, from_date, to_date)

    parts    = db_user["name"].split()
    initials = "".join(p[0].upper() for p in parts[:2])
    try:
        member_since = date.fromisoformat(db_user["created_at"][:10]).strftime("%B %Y")
    except (ValueError, TypeError):
        member_since = "—"

    user = {
        "name":         db_user["name"],
        "email":        db_user["email"],
        "member_since": member_since,
        "initials":     initials,
    }

    # Avoid division by zero; categories will be empty anyway when total is 0
    total = stats["total_spent"] if stats["total_spent"] else 1
    categories = [
        {
            "name":   row["category"],
            "amount": f"₹{row['total']:.2f}",
            "pct":    round(row["total"] / total * 100),
        }
        for row in raw_categories
    ]

    display_stats = {
        "total_spent":       f"₹{stats['total_spent']:.2f}",
        "transaction_count": stats["transaction_count"],
        "top_category":      stats["top_category"] or "—",
    }

    return render_template(
        "profile.html",
        user=user,
        expenses=expenses,
        stats=display_stats,
        categories=categories,
        active_filter=active_filter,
        from_date=raw_from,
        to_date=raw_to,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template(
            "add_expense.html",
            today=date.today().isoformat(),
            categories=sorted(_VALID_CATEGORIES),
        )

    amount_raw   = request.form.get("amount", "").strip()
    category     = request.form.get("category", "").strip()
    expense_date = request.form.get("date", "").strip()
    description  = request.form.get("description", "").strip()

    def _error(msg):
        return render_template(
            "add_expense.html",
            error=msg,
            amount=amount_raw,
            category=category,
            date=expense_date,
            description=description,
            today=date.today().isoformat(),
            categories=sorted(_VALID_CATEGORIES),
        )

    try:
        amount = float(amount_raw)
        if amount <= 0 or amount > 1_000_000:
            raise ValueError
    except (ValueError, TypeError):
        return _error("Amount must be between ₹0.01 and ₹10,00,000.")

    if category not in _VALID_CATEGORIES:
        return _error("Please select a valid category.")

    if description and len(description) > 200:
        return _error("Description must be 200 characters or fewer.")

    if not expense_date:
        expense_date = date.today().isoformat()
    else:
        try:
            parsed_date = date.fromisoformat(expense_date)
        except ValueError:
            return _error("Please enter a valid date.")
        if parsed_date > date.today():
            return _error("Expense date cannot be in the future.")

    create_expense(session["user_id"], amount, category, expense_date, description)
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


with app.app_context():
    init_db()
    seed_db()


if __name__ == "__main__":
    app.run(debug=True, port=5001)

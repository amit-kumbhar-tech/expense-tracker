import sqlite3

from flask import Flask, render_template, request, session, redirect, url_for, abort
from werkzeug.security import generate_password_hash, check_password_hash

from database.db import get_db, init_db, seed_db, get_user_by_email, get_user_by_id, create_user

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"


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

    session["user_id"]   = user_id
    session["user_name"] = name
    return redirect(url_for("landing"))


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

    name = "Demo User"
    parts = name.split()
    initials = "".join(p[0].upper() for p in parts[:2])

    user = {
        "name": name,
        "email": "demo@spendly.com",
        "member_since": "January 2026",
        "initials": initials,
    }
    stats = {
        "total_spent": "₹346.25",
        "transaction_count": 8,
        "top_category": "Bills",
    }
    transactions = [
        {"date": "May 22, 2026", "description": "Dinner",        "category": "Food",          "amount": "₹18.75"},
        {"date": "May 18, 2026", "description": "Miscellaneous", "category": "Other",         "amount": "₹10.00"},
        {"date": "May 15, 2026", "description": "Groceries",     "category": "Shopping",      "amount": "₹85.00"},
        {"date": "May 12, 2026", "description": "Movie tickets", "category": "Entertainment", "amount": "₹25.00"},
        {"date": "May 10, 2026", "description": "Pharmacy",      "category": "Health",        "amount": "₹30.00"},
    ]
    categories = [
        {"name": "Bills",         "amount": "₹120.00", "pct": 35},
        {"name": "Shopping",      "amount": "₹85.00",  "pct": 25},
        {"name": "Transport",     "amount": "₹45.00",  "pct": 13},
        {"name": "Food",          "amount": "₹31.25",  "pct": 9},
        {"name": "Health",        "amount": "₹30.00",  "pct": 9},
        {"name": "Entertainment", "amount": "₹25.00",  "pct": 7},
        {"name": "Other",         "amount": "₹10.00",  "pct": 3},
    ]
    return render_template("profile.html",
                           user=user,
                           stats=stats,
                           transactions=transactions,
                           categories=categories)


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


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

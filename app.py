from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
import re
from bson import ObjectId
from datetime import datetime
import csv
from io import StringIO
from flask import Response
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
bcrypt = Bcrypt(app)

app.secret_key = os.getenv('SECRET_KEY')
client = MongoClient(os.getenv('MONGO_URI'))

db = client['expense_tracker']
users_collection = db['users']
expenses_collection = db['expenses']
balances_collection = db['balances']

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if users_collection.find_one({"username": username}):
            flash("Username already exists. Try another.", "error")
            return redirect(url_for('signup'))
        if users_collection.find_one({"email": email}):
            flash("Email already registered. Try another.", "error")
            return redirect(url_for('signup'))
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for('signup'))
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash("Invalid email format.", "error")
            return redirect(url_for('signup'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        users_collection.insert_one({
            "username": username,
            "email": email,
            "phone": phone,
            "password": hashed_password
        })
        flash("Signup successful! Please login.", "success")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = users_collection.find_one({"username": username})
        if not user:
            flash("User not found. Please signup.", "error")
            return redirect(url_for('login'))
        if not bcrypt.check_password_hash(user['password'], password):
            flash("Incorrect password.", "error")
            return redirect(url_for('login'))

        session['username'] = username
        return redirect(url_for('dashboard'))

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    total_expenses = get_current_month_expense_total()
    current_balance = get_current_balance()

    # Debugging - Print the total expenses value
    print(f"Total Expenses: ₹{total_expenses:.2f}")

    return render_template('dashboard.html', username=username, total_expenses=total_expenses, current_balance=current_balance)


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))

@app.route("/add_expense", methods=["GET", "POST"])
def add_expense():
    if request.method == "POST":
        category = request.form["category"]
        amount = float(request.form["amount"])
        description = request.form["description"]
        date = request.form["date"]

        # Try parsing the date in both formats
        try:
            date_obj = datetime.strptime(date, "%d-%m-%Y")
        except ValueError:
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                flash("Invalid date format. Please use DD-MM-YYYY or YYYY-MM-DD.", "error")
                return redirect(url_for('add_expense'))

        # Insert the expense into the database with the converted datetime
        expenses_collection.insert_one({
            "category": category,
            "amount": amount,
            "description": description,
            "date": date_obj,
            "type": "expense"
        })

        # Update current balance
        current_balance = get_current_balance()
        new_balance = current_balance - amount
        balances_collection.update_one({"_id": 1}, {"$set": {"balance": new_balance}})

        # Recalculate total expenses for the current month
        total_expenses = get_current_month_expense_total()

        # Debugging - Check the total expenses calculated
        print(f"Total Expenses this Month: ₹{total_expenses:.2f}")

        # Flash success message
        flash("Expense added successfully!", "success")

        # Redirect to dashboard with updated total expenses
        return redirect(url_for("dashboard", total_expenses=total_expenses))

    return render_template("add_expense.html")


@app.route("/view_expenses", methods=["GET", "POST"])
def view_expenses():
    category_filter = request.args.get("category")

    query_filter = {}

    if category_filter:
        query_filter["category"] = category_filter

    expenses = list(expenses_collection.find(query_filter))

    for expense in expenses:
        if isinstance(expense['date'], str):
            try:
                expense['date'] = datetime.strptime(expense['date'], '%Y-%m-%d')
            except ValueError:
                # If the date string is not in the expected format, we'll set it to None
                expense['date'] = None
        
        if isinstance(expense['date'], datetime):
            expense['date'] = expense['date'].strftime('%d-%m-%Y')
        else:
            # If it's neither a datetime nor a valid date string, we'll set it to 'N/A'
            expense['date'] = 'N/A'

        # Ensure amount is a float
        expense['amount'] = float(expense['amount'])

    categories = expenses_collection.distinct("category")

    return render_template("view_expenses.html", expenses=expenses, categories=categories)


@app.route("/edit_expense/<string:id>", methods=["GET", "POST"])
def edit_expense(id):
    expense = expenses_collection.find_one({"_id": ObjectId(id)})

    if request.method == "POST":
        updated_category = request.form["category"]
        updated_amount = request.form["amount"]
        updated_description = request.form["description"]
        updated_date = request.form["date"]

        expenses_collection.update_one({"_id": ObjectId(id)}, {
            "$set": {
                "category": updated_category,
                "amount": updated_amount,
                "description": updated_description,
                "date": updated_date
            }
        })
        flash("Expense updated successfully!", "success")
        return redirect(url_for("view_expenses"))

    return render_template("edit_expense.html", expense=expense)

@app.route("/delete_expense/<string:id>")
def delete_expense(id):
    expenses_collection.delete_one({"_id": ObjectId(id)})
    flash("Expense deleted successfully!", "danger")
    return redirect(url_for("view_expenses"))


def get_current_month_expense_total():
    # Start of the current month
    start_date = datetime(datetime.now().year, datetime.now().month, 1)
    # Start of the next month
    end_date = datetime(datetime.now().year, datetime.now().month + 1, 1)

    # Query expenses for the current month only
    expenses = expenses_collection.find({
        "date": {"$gte": start_date, "$lt": end_date},  # Ensure we are filtering for the current month
        "type": "expense"  # Only consider expenses, not income
    })
    
    # Sum the amounts, ensuring zero expenses are considered correctly
    total_expenses = sum(expense['amount'] for expense in expenses)
    
    # Debugging - Print out the expense details for verification
    print("Total Expenses this Month (including zero entries): ₹{:.2f}".format(total_expenses))

    return total_expenses



@app.route("/export_expenses", methods=["GET"])
def export_expenses():
    expenses = list(expenses_collection.find())

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Category", "Amount", "Description", "Date"])

    for expense in expenses:
        # Ensure date is a datetime object, if it's not already
        if isinstance(expense["date"], str):
            expense["date"] = datetime.strptime(expense["date"], "%Y-%m-%d")  # Adjust the format as per your data
            
        writer.writerow([
            expense["category"],
            expense["amount"],
            expense["description"],
            expense["date"].strftime("%Y-%m-%d")  # Now it's safe to use strftime
        ])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=expenses.csv"}
    )

@app.route("/add_balance", methods=["POST"])
def add_balance():
    if request.method == "POST":
        income_amount = float(request.form["income_amount"])

        expenses_collection.insert_one({
            "category": "Income",
            "amount": income_amount,
            "description": "Salary / Income",
            "date": datetime.now(),
            "type": "income"
        })

        current_balance = balances_collection.find_one({"_id": 1})
        if current_balance:
            new_balance = current_balance['balance'] + income_amount
            balances_collection.update_one({"_id": 1}, {"$set": {"balance": new_balance}})
        else:
            balances_collection.insert_one({"_id": 1, "balance": income_amount})

        flash("Balance added successfully!", "success")
        return redirect(url_for("dashboard"))

def get_current_balance():
    current_balance = balances_collection.find_one({"_id": 1})
    if current_balance:
        return current_balance['balance']
    else:
        return 0

if __name__ == '__main__':
    app.run(debug=True)
from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from mysql.connector import Error
from datetime import datetime, date
import random
import os

# -----------------------------
# Config
# -----------------------------
app = Flask(__name__)
app.secret_key = "sanjay_bank_flask_secret_1204"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASS"),
    "database": os.environ.get("DB_NAME"),
    "port": int(os.environ.get("DB_PORT")),
    "ssl_disabled": False
}


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def init_schema():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_number BIGINT PRIMARY KEY,
            name VARCHAR(80) NOT NULL,
            dob DATE NOT NULL,
            phone VARCHAR(15) NOT NULL,
            aadhar VARCHAR(12) NOT NULL UNIQUE,
            pan VARCHAR(10) NOT NULL UNIQUE,
            pin VARCHAR(6) NOT NULL,
            balance DOUBLE NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            account_number BIGINT NOT NULL,
            txn_type ENUM('DEPOSIT','WITHDRAW','TRANSFER_OUT','TRANSFER_IN','ACCOUNT_CREATE','PIN_CHANGE') NOT NULL,
            amount DOUBLE NOT NULL,
            note VARCHAR(255),
            counterparty BIGINT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_number) REFERENCES accounts(account_number)
        );
    """)

    conn.commit()
    cur.close()
    conn.close()


def calc_age(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def generate_account_number(cur) -> int:
    while True:
        acc = random.randint(2000000000, 9999999999)
        cur.execute("SELECT 1 FROM accounts WHERE account_number=%s", (acc,))
        if not cur.fetchone():
            return acc


initialized = False


@app.before_request
def before_first_request():
    global initialized
    if not initialized:
        init_schema()
        initialized = True


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/explore")
def explore():
    return render_template("explore.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name").strip()
        dob_str = request.form.get("dob").strip()
        phone = request.form.get("phone").strip()
        aadhar = request.form.get("aadhar").strip()
        pan = request.form.get("pan").strip().upper()
        pin = request.form.get("pin").strip()

        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid DOB format (YYYY-MM-DD).", "danger")
            return redirect(url_for("register"))

        if calc_age(dob) < 18:
            flash("Only users 18+ can open an account.", "danger")
            return redirect(url_for("register"))

        if not (pin.isdigit() and len(pin) == 4):
            flash("PIN must be exactly 4 digits.", "danger")
            return redirect(url_for("register"))

        try:
            init_amt = float(request.form.get("initial_deposit"))
            if init_amt < 1000:
                flash("Minimum initial deposit is ₹1000.", "danger")
                return redirect(url_for("register"))
        except:
            flash("Invalid deposit amount.", "danger")
            return redirect(url_for("register"))

        conn = get_db()
        cur = conn.cursor()
        try:
            acc_no = generate_account_number(cur)

            cur.execute("""
                INSERT INTO accounts (account_number, name, dob, phone, aadhar, pan, pin, balance)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (acc_no, name, dob, phone, aadhar, pan, pin, init_amt))

            cur.execute("""
                INSERT INTO transactions(account_number, txn_type, amount, note)
                VALUES (%s,'ACCOUNT_CREATE',%s,%s)
            """, (acc_no, init_amt, "Initial deposit"))

            conn.commit()
            flash(f"Account created! Your Account Number is {acc_no}", "success")
            return redirect(url_for("login"))
        except Error as e:
            conn.rollback()
            flash(f"Error: {e}", "danger")
        finally:
            cur.close()
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        id_value = request.form.get("id_value").strip()
        pin = request.form.get("pin").strip()

        if not (pin.isdigit() and len(pin) == 4):
            flash("PIN must be 4 digits.", "danger")
            return redirect(url_for("login"))

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT account_number FROM accounts WHERE (account_number=%s OR phone=%s) AND pin=%s",
                    (id_value, id_value, pin))
        row = cur.fetchone()

        cur.close()
        conn.close()

        if row:
            session["acc_no"] = row[0]
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid Login.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
def dashboard():
    if "acc_no" not in session:
        return redirect(url_for("login"))

    acc_no = session["acc_no"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, balance FROM accounts WHERE account_number=%s", (acc_no,))
    name, balance = cur.fetchone()
    cur.close()
    conn.close()

    return render_template("dashboard.html", name=name, balance=balance, acc_no=acc_no)


@app.route("/deposit", methods=["GET", "POST"])
def deposit():
    if "acc_no" not in session:
        return redirect(url_for("login"))

    acc_no = session["acc_no"]

    if request.method == "POST":
        amt = float(request.form.get("amount"))
        if amt <= 0:
            flash("Amount must be positive.", "danger")
            return redirect(url_for("deposit"))

        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE accounts SET balance = balance + %s WHERE account_number=%s", (amt, acc_no))
        cur.execute("INSERT INTO transactions VALUES (NULL,%s,'DEPOSIT',%s,'Online deposit',NULL)", (acc_no, amt))
        conn.commit()
        cur.close()
        conn.close()

        flash("Deposit successful!", "success")
        return redirect(url_for("dashboard"))

    return render_template("deposit.html")


@app.route("/withdraw", methods=["GET", "POST"])
def withdraw():
    if "acc_no" not in session:
        return redirect(url_for("login"))

    acc_no = session["acc_no"]

    if request.method == "POST":
        amt = float(request.form.get("amount"))
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT balance FROM accounts WHERE account_number=%s", (acc_no,))
        bal = cur.fetchone()[0]

        if amt > bal:
            flash("Insufficient balance.", "danger")
        else:
            new_bal = bal - amt
            cur.execute("UPDATE accounts SET balance=%s WHERE account_number=%s", (new_bal, acc_no))
            cur.execute("INSERT INTO transactions VALUES (NULL,%s,'WITHDRAW',%s,'Online withdrawal',NULL)",
                        (acc_no, amt))
            conn.commit()
            flash("Withdrawal successful!", "success")

        cur.close()
        conn.close()
        return redirect(url_for("dashboard"))

    return render_template("withdraw.html")


@app.route("/transfer", methods=["GET", "POST"])
def transfer():
    if "acc_no" not in session:
        return redirect(url_for("login"))

    acc_no = session["acc_no"]

    if request.method == "POST":
        to_acc = int(request.form.get("to_acc"))
        amt = float(request.form.get("amount"))

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT balance FROM accounts WHERE account_number=%s", (acc_no,))
        bal = cur.fetchone()[0]

        if amt > bal:
            flash("Insufficient balance.", "danger")
        else:
            cur.execute("UPDATE accounts SET balance = balance - %s WHERE account_number=%s", (amt, acc_no))
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE account_number=%s", (amt, to_acc))

            cur.execute("""INSERT INTO transactions VALUES (NULL,%s,'TRANSFER_OUT',%s,'Transfer to %s',%s)""",
                        (acc_no, amt, to_acc, to_acc))

            cur.execute("""INSERT INTO transactions VALUES (NULL,%s,'TRANSFER_IN',%s,'Received from %s',%s)""",
                        (to_acc, amt, acc_no, acc_no))

            conn.commit()
            flash("Transfer successful!", "success")

        cur.close()
        conn.close()
        return redirect(url_for("dashboard"))

    return render_template("transfer.html")


# ATM Login
@app.route("/atm", methods=["GET", "POST"])
def atm_login():
    if request.method == "POST":
        pin = request.form.get("pin").strip()

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT account_number FROM accounts WHERE pin=%s", (pin,))
        row = cur.fetchone()

        cur.close()
        conn.close()

        if row:
            session["atm_acc"] = row[0]
            return redirect(url_for("atm_menu"))
        else:
            flash("Invalid PIN.", "danger")

    return render_template("atm_login.html")


@app.route("/atm/menu")
def atm_menu():
    if "atm_acc" not in session:
        return redirect(url_for("atm_login"))
    return render_template("atm_menu.html")


@app.route("/atm/withdraw", methods=["GET", "POST"])
def atm_withdraw():
    if "atm_acc" not in session:
        return redirect(url_for("atm_login"))
    acc = session["atm_acc"]

    if request.method == "POST":
        amt = float(request.form.get("amount"))

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT balance FROM accounts WHERE account_number=%s", (acc,))
        bal = cur.fetchone()[0]

        if amt <= bal:
            cur.execute("UPDATE accounts SET balance=%s WHERE account_number=%s", (bal - amt, acc))
            conn.commit()
            flash("Cash withdrawn!", "success")
        else:
            flash("Insufficient balance!", "danger")

        cur.close()
        conn.close()

    return render_template("atm_withdraw.html")


@app.route("/atm/deposit", methods=["GET", "POST"])
def atm_deposit():
    if "atm_acc" not in session:
        return redirect(url_for("atm_login"))
    acc = session["atm_acc"]

    if request.method == "POST":
        amt = float(request.form.get("amount"))
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE accounts SET balance = balance + %s WHERE account_number=%s", (amt, acc))
        conn.commit()
        cur.close()
        conn.close()
        flash("Deposit successful!", "success")

    return render_template("atm_deposit.html")


@app.route("/atm/balance")
def atm_balance():
    if "atm_acc" not in session:
        return redirect(url_for("atm_login"))

    acc = session["atm_acc"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM accounts WHERE account_number=%s", (acc,))
    bal = cur.fetchone()[0]
    cur.close()
    conn.close()

    return render_template("atm_balance.html", balance=bal)


@app.route("/atm/logout")
def atm_logout():
    session.pop("atm_acc", None)
    return redirect(url_for("atm_login"))


# Change PIN
@app.route("/change_pin", methods=["GET", "POST"])
def change_pin():
    if "acc_no" not in session:
        return redirect(url_for("login"))

    acc_no = session["acc_no"]

    if request.method == "POST":
        new_pin = request.form.get("new_pin")
        confirm_pin = request.form.get("confirm_pin")

        if new_pin != confirm_pin or not new_pin.isdigit() or len(new_pin) != 4:
            flash("Invalid PIN.", "danger")
            return redirect(url_for("change_pin"))

        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE accounts SET pin=%s WHERE account_number=%s", (new_pin, acc_no))
        cur.execute("INSERT INTO transactions VALUES (NULL,%s,'PIN_CHANGE',0,'PIN Changed',NULL)", (acc_no,))
        conn.commit()
        cur.close()
        conn.close()

        flash("PIN changed successfully!", "success")
        return redirect(url_for("dashboard"))

    return render_template("change_pin.html")


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        phone = request.form.get("phone")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT account_number FROM accounts WHERE phone=%s", (phone,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            flash(f"Your Account Number is: {row[0]}", "success")
        else:
            flash("No account found with this phone.", "danger")

    return render_template("forgot.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

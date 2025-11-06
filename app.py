from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from mysql.connector import Error
from datetime import datetime, date
import random
import os
import requests

# -----------------------------
# Config
# -----------------------------
app = Flask(__name__)
app.secret_key = "sanjay_bank_flask_secret_1204"  # change if you like

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "sanjay1231",  # set by you
    "database": "sanjay_bank"
}

SECRETS_FILE = "fast2sms_key.txt"
FAST2SMS_ENDPOINT = "https://www.fast2sms.com/dev/bulkV2"


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def init_schema():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
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
        """
    )
    cur.execute(
        """
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
        """
    )
    conn.commit()
    cur.close(); conn.close()


def read_fast2sms_key() -> str:
    if os.path.exists(SECRETS_FILE):
        try:
            with open(SECRETS_FILE, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if k:
                    return k
        except Exception:
            pass
    # No key present: show a one-time hint in logs (not to user directly)
    print("Fast2SMS key missing. Place it in fast2sms_key.txt (same folder as app.py).")
    return ""


def send_sms(mobile: str, message: str):
    try:
        api_key = read_fast2sms_key()
        if not api_key:
            return
        headers = {'authorization': api_key}
        data = {
            'route': 'v3',
            'sender_id': 'TXTIND',
            'message': message,
            'language': 'english',
            'flash': 0,
            'numbers': mobile
        }
        resp = requests.post(FAST2SMS_ENDPOINT, headers=headers, data=data, timeout=10)
        if resp.status_code != 200:
            print(f"(SMS) Non-200 response: {resp.status_code}")
    except Exception as e:
        print(f"(SMS) Failed to send: {e}")


def calc_age(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def generate_account_number(cur) -> int:
    while True:
        acc = random.randint(2000000000, 9999999999)
        cur.execute("SELECT 1 FROM accounts WHERE account_number=%s", (acc,))
        if not cur.fetchone():
            return acc


# Ensure DB tables only initialize once
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
        name = request.form.get("name","").strip()
        dob_str = request.form.get("dob","").strip()
        phone = request.form.get("phone","").strip()
        aadhar = request.form.get("aadhar","").strip()
        pan = request.form.get("pan","").strip().upper()
        pin = request.form.get("pin","").strip()

        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid DOB format (YYYY-MM-DD).", "danger")
            return redirect(url_for("register"))

        if calc_age(dob) < 18:
            flash("Only users 18+ can create an account.", "danger")
            return redirect(url_for("register"))

        if not (pin.isdigit() and len(pin) == 4):
            flash("PIN must be exactly 4 digits.", "danger")
            return redirect(url_for("register"))

        try:
            init_amt = float(request.form.get("initial_deposit","0"))
            if init_amt < 1000:
                flash("Minimum initial deposit is ₹1000.", "danger")
                return redirect(url_for("register"))
        except ValueError:
            flash("Invalid initial deposit.", "danger")
            return redirect(url_for("register"))

        conn = get_db(); cur = conn.cursor()
        try:
            acc_no = generate_account_number(cur)
            cur.execute("""
                INSERT INTO accounts (account_number, name, dob, phone, aadhar, pan, pin, balance)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (acc_no, name, dob, phone, aadhar, pan, pin, init_amt))
            cur.execute("""
                INSERT INTO transactions (account_number, txn_type, amount, note)
                VALUES (%s,'ACCOUNT_CREATE',%s,%s)
            """, (acc_no, init_amt, "Initial deposit on account creation"))
            conn.commit()
            flash(f"Account created! Your Account Number is {acc_no}", "success")
            send_sms(phone, f"Sanjay Bank: Account {acc_no} created. Opening balance ₹{init_amt:.2f}.")
            return redirect(url_for("login"))
        except Error as e:
            conn.rollback()
            flash(f"Failed to create account: {e}", "danger")
        finally:
            cur.close(); conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    # L3: Login by (Account Number + PIN) OR (Phone + PIN)
    if request.method == "POST":
        id_value = request.form.get("id_value","").strip()
        pin = request.form.get("pin","").strip()
        if not (pin.isdigit() and len(pin) == 4):
            flash("PIN must be 4 digits.", "danger")
            return redirect(url_for("login"))

        conn = get_db(); cur = conn.cursor()
        try:
            # Try account number
            acc_no = None
            if id_value.isdigit() and len(id_value) >= 6:
                cur.execute("SELECT account_number, phone FROM accounts WHERE account_number=%s AND pin=%s",
                            (int(id_value), pin))
                row = cur.fetchone()
                if row:
                    acc_no = row[0]

            if acc_no is None:
                # Try phone
                cur.execute("SELECT account_number, phone FROM accounts WHERE phone=%s AND pin=%s",
                            (id_value, pin))
                row = cur.fetchone()
                if row:
                    acc_no = row[0]

            if acc_no is None:
                flash("Invalid credentials.", "danger")
                return redirect(url_for("login"))

            session["acc_no"] = acc_no
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        finally:
            cur.close(); conn.close()

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("home"))


def require_login():
    if "acc_no" not in session:
        flash("Please login first.", "warning")
        return False
    return True


@app.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("login"))
    acc_no = session["acc_no"]
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT name, balance FROM accounts WHERE account_number=%s", (acc_no,))
    row = cur.fetchone()
    cur.close(); conn.close()
    name, balance = row if row else ("User", 0.0)
    return render_template("dashboard.html", name=name, balance=balance, acc_no=acc_no)


@app.route("/deposit", methods=["GET","POST"])
def deposit():
    if not require_login():
        return redirect(url_for("login"))
    acc_no = session["acc_no"]
    if request.method == "POST":
        try:
            amt = float(request.form.get("amount","0"))
        except ValueError:
            flash("Invalid amount.", "danger")
            return redirect(url_for("deposit"))
        if amt <= 0:
            flash("Amount must be positive.", "danger")
            return redirect(url_for("deposit"))
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE account_number=%s", (amt, acc_no))
            cur.execute("INSERT INTO transactions (account_number, txn_type, amount, note) VALUES (%s,'DEPOSIT',%s,%s)",
                        (acc_no, amt, "Online deposit"))
            cur.execute("SELECT phone FROM accounts WHERE account_number=%s", (acc_no,))
            phone = cur.fetchone()[0]
            conn.commit()
            flash("Deposit successful!", "success")
            send_sms(phone, f"Sanjay Bank: ₹{amt:.2f} deposited. A/c {acc_no}.")
            return redirect(url_for("dashboard"))
        except Error as e:
            conn.rollback(); flash(f"Deposit failed: {e}", "danger")
        finally:
            cur.close(); conn.close()
    return render_template("deposit.html")


@app.route("/withdraw", methods=["GET","POST"])
def withdraw():
    if not require_login():
        return redirect(url_for("login"))
    acc_no = session["acc_no"]
    if request.method == "POST":
        try:
            amt = float(request.form.get("amount","0"))
        except ValueError:
            flash("Invalid amount.", "danger")
            return redirect(url_for("withdraw"))
        if amt <= 0:
            flash("Amount must be positive.", "danger")
            return redirect(url_for("withdraw"))
        conn = get_db(); cur = conn.cursor()
        try:
            conn.start_transaction()
            cur.execute("SELECT balance, phone FROM accounts WHERE account_number=%s FOR UPDATE", (acc_no,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Account not found")
            bal, phone = row
            if bal < amt:
                raise ValueError("Insufficient balance")
            cur.execute("UPDATE accounts SET balance = balance - %s WHERE account_number=%s", (amt, acc_no))
            cur.execute("INSERT INTO transactions (account_number, txn_type, amount, note) VALUES (%s,'WITHDRAW',%s,%s)",
                        (acc_no, amt, "Online withdrawal"))
            conn.commit()
            flash("Withdrawal successful!", "success")
            send_sms(phone, f"Sanjay Bank: ₹{amt:.2f} withdrawn. A/c {acc_no}.")
            return redirect(url_for("dashboard"))
        except Exception as e:
            conn.rollback(); flash(f"Withdrawal failed: {e}", "danger")
        finally:
            cur.close(); conn.close()
    return render_template("withdraw.html")


@app.route("/transfer", methods=["GET","POST"])
def transfer():
    if not require_login():
        return redirect(url_for("login"))
    acc_no = session["acc_no"]

    if request.method == "POST":
        try:
            to_acc = int(request.form.get("to_acc", "0"))
            amt = float(request.form.get("amount", "0"))
        except ValueError:
            flash("Invalid account number or amount.", "danger")
            return redirect(url_for("transfer"))

        if to_acc == acc_no:
            flash("Cannot transfer to your own account.", "warning")
            return redirect(url_for("transfer"))

        if amt <= 0:
            flash("Amount must be positive.", "danger")
            return redirect(url_for("transfer"))

        conn = get_db()
        cur = conn.cursor()

        try:
            conn.start_transaction()

            # Lock source account
            cur.execute("SELECT balance, phone FROM accounts WHERE account_number=%s FOR UPDATE", (acc_no,))
            src = cur.fetchone()
            if not src:
                raise ValueError("Source account not found")
            src_bal, src_phone = src

            if src_bal < amt:
                raise ValueError("Insufficient balance")

            # Lock destination account
            cur.execute("SELECT phone FROM accounts WHERE account_number=%s FOR UPDATE", (to_acc,))
            dst = cur.fetchone()
            if not dst:
                raise ValueError("Destination account not found")
            dst_phone = dst[0]

            # Perform transfer
            cur.execute("UPDATE accounts SET balance = balance - %s WHERE account_number=%s", (amt, acc_no))
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE account_number=%s", (amt, to_acc))

            # Record logs
            cur.execute("""
                INSERT INTO transactions (account_number, txn_type, amount, note, counterparty)
                VALUES (%s,'TRANSFER_OUT',%s,%s,%s)
            """, (acc_no, amt, "Online transfer to another account", to_acc))

            cur.execute("""
                INSERT INTO transactions (account_number, txn_type, amount, note, counterparty)
                VALUES (%s,'TRANSFER_IN',%s,%s,%s)
            """, (to_acc, amt, "Online transfer received", acc_no))

            conn.commit()
            flash("✅ Transfer successful!", "success")

            # SMS Alerts
            send_sms(src_phone, f"Sanjay Bank: ₹{amt:.2f} sent to {to_acc}. A/c {acc_no}.")
            send_sms(dst_phone, f"Sanjay Bank: ₹{amt:.2f} received from {acc_no}. A/c {to_acc}.")

            return redirect(url_for("dashboard"))

        except Exception as e:
            conn.rollback()
            flash(f"❌ Transfer failed: {e}", "danger")
        finally:
            cur.close()
            conn.close()

    return render_template("transfer.html")

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
            acc = row[0]
            flash(f"✅ Your Account Number is: {acc}", "success")
        else:
            flash("❌ No account found with this phone number.", "danger")

    return render_template("forgot.html")


if __name__ == "__main__":
    app.run(debug=True)



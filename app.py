from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import hashlib
import random
from flask import jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import logging
import os





app = Flask(__name__)

app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = 'your_secret_key'
print("🚀 اجرای `init_db()` برای ایجاد جداول...")
init_db()
print("✅ دیتابیس ایجاد شد!")

# انتخاب مسیر دیتابیس بر اساس محیط اجرا (لوکال یا Render)
if os.getenv("RENDER"):  
    DATABASE_PATH = "/data/database.db"  # مسیر برای محیط Render
else:
    DATABASE_PATH = "database.db"  # مسیر برای محیط لوکال

def get_db():
    """
    اتصال به پایگاه داده و بازگشت شیء اتصال.
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)  # اتصال به دیتابیس
        conn.row_factory = sqlite3.Row  # تنظیم برای بازگرداندن نتایج به‌صورت دیکشنری
        return conn
    except sqlite3.Error as e:
        print(f"❌ خطا در اتصال به دیتابیس: {e}")
        return None

def init_db():
    """
    تابع برای ایجاد جداول دیتابیس در صورت نیاز.
    """
    conn = get_db()
    if conn is not None:
        cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        first_name TEXT NOT NULL,
                        last_name TEXT NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL,
                        referral_link TEXT UNIQUE,
                        referrer_id INTEGER,
                        total_balance REAL DEFAULT 0,
                        mining_hashed INTEGER DEFAULT 0,
                        mining_speed INTEGER DEFAULT 5,
                        level INTEGER DEFAULT 1,
                        FOREIGN KEY(referrer_id) REFERENCES users(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS referrals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        referral_user_id INTEGER,
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(referral_user_id) REFERENCES users(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        amount REAL,
                        FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    conn.close()
# ایجاد پایگاه داده و جدول‌های مورد نیاز
def update_database():
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()

        # دریافت لیست ستون‌های موجود در جدول users
        cursor.execute("PRAGMA table_info(users)")
        existing_columns = {col[1] for col in cursor.fetchall()}  # استفاده از مجموعه (set)

        # تعریف ستون‌هایی که باید اضافه شوند (فقط در صورتی که وجود نداشته باشند)
        columns_to_add = {
            "total_balance": "REAL DEFAULT 0",
            "mining_hashed": "INTEGER DEFAULT 0",
            "mining_speed": "INTEGER DEFAULT 5",
            "level": "INTEGER DEFAULT 1",
            "last_balance_check": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "referral_rewards": "REAL DEFAULT 0",
            "previous_balance": "REAL DEFAULT 0",  # اضافه شدن مقدار قبلی موجودی
            "previous_referral": "REAL DEFAULT 0"  # اضافه شدن مقدار قبلی درآمد ریفرال
        }

        # بررسی و اضافه کردن ستون‌های جدید در صورت نیاز
        for column, data_type in columns_to_add.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {column} {data_type};")

        conn.commit()

    except sqlite3.Error as e:
        print(f"❌ خطا در به‌روزرسانی پایگاه داده: {e}")

    finally:
        conn.close()


def update_balances():
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()

        # دریافت اطلاعات کاربران
        cursor.execute("SELECT id, total_balance, previous_balance, referral_rewards, previous_referral FROM users")
        users = cursor.fetchall()

        for user in users:
            user_id, total_balance, previous_balance, referral_rewards, previous_referral = user

            # محاسبه تغییرات درآمد (افزایش موجودی نسبت به بررسی قبلی)
            balance_change = total_balance - previous_balance

            # محاسبه تغییرات درآمد ریفرال
            referral_change = referral_rewards - previous_referral

            if balance_change > 0 or referral_change > 0:
                # اضافه کردن فقط تغییرات درآمد ریفرال به کل درآمد
                new_balance = total_balance + referral_change  

                # به‌روزرسانی مقدار درآمد کل و مقدار قبلی موجودی و ریفرال
                cursor.execute("UPDATE users SET total_balance = ?, previous_balance = ?, previous_referral = ? WHERE id = ?", 
                               (new_balance, total_balance, referral_rewards, user_id))

        conn.commit()

    except sqlite3.Error as e:
        print(f"❌ خطا در به‌روزرسانی موجودی کاربران: {e}")

    finally:
        conn.close()


# اجرای تابع‌های پایگاه داده و آپدیت موجودی کاربران
update_database()


TELEGRAM_BOT_TOKEN = "7626749475:AAE63tGqDsegeDGFDKR07bKOLwYEghePoIg"
TELEGRAM_CHAT_ID = "5293309149"

# تابع ارسال پیام به تلگرام
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    requests.post(url, json=payload)

# مدیریت درخواست برداشت
@app.route('/withdraw', methods=['POST'])
def withdraw():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "لطفاً ابتدا وارد شوید!"}), 403  # بررسی ورود کاربر

    user_id = session.get("user_id")  # مقدار user_id را از session دریافت کن
    if not user_id:
        return jsonify({"status": "error", "message": "آیدی کاربر نامعتبر است!"}), 400

    data = request.json
    amount = float(data.get("amount"))
    phone = data.get("phone")

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT total_balance FROM users WHERE id=?", (user_id,))
    user = cursor.fetchone()

    if user is None:
        return jsonify({"status": "error", "message": "کاربر پیدا نشد!"}), 404

    current_balance = user[0]

    if current_balance >= amount:
        new_balance = current_balance - amount  # محاسبه موجودی جدید
        cursor.execute("UPDATE users SET total_balance = ? WHERE id = ?", (new_balance, user_id))
        conn.commit()

        # ارسال پیام به تلگرام همراه آیدی کاربر
        message = f"📢 درخواست برداشت جدید:\n👤 آیدی کاربر: {user_id}\n💰 مقدار: {amount}\n📞 شماره تلفن: {phone}"
        send_telegram_message(message)

        return jsonify({"status": "success", "message": "درخواست برداشت ثبت شد!", "new_balance": new_balance})
    else:
        return jsonify({"status": "error", "message": "موجودی کافی نیست!"}), 400

    conn.close()
# محاسبه پاداش‌های ریفرال
def calculate_referral_rewards():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # دریافت اطلاعات کاربران شامل موجودی کل، موجودی قبلی و آی‌دی معرف
    cursor.execute("SELECT id, total_balance, previous_balance, referrer_id FROM users")
    users = cursor.fetchall()

    for user in users:
        user_id, current_balance, previous_balance, referrer_id = user

        # مقداردهی اولیه previous_balance در اولین اجرا
        if previous_balance is None:
            cursor.execute("UPDATE users SET previous_balance = ? WHERE id=?", (current_balance, user_id))
            continue

        # محاسبه تغییرات در موجودی
        balance_difference = current_balance - previous_balance

        # اگر موجودی افزایش داشته باشد و کاربر معرف داشته باشد
        if balance_difference > 0 and referrer_id:
            reward = balance_difference * 0.1  # محاسبه 10٪ افزایش موجودی
            cursor.execute("UPDATE users SET referral_rewards = referral_rewards + ? WHERE id=?", (reward, referrer_id))

        # به‌روزرسانی مقدار previous_balance برای بررسی بعدی
        cursor.execute("UPDATE users SET previous_balance = ? WHERE id=?", (current_balance, user_id))

    conn.commit()
    conn.close()
    update_balances()

# ایجاد زمان‌بند برای اجرای خودکار محاسبه پاداش‌های ریفرال
scheduler = BackgroundScheduler(timezone=None)
scheduler.add_job(calculate_referral_rewards, 'interval', seconds=600)
scheduler.start()
# تولید شناسه ریفرال 6 رقمی یکتا
def generate_referral_id():
    while True:
        referral_id = random.randint(100000, 999999)
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE referral_id=?", (referral_id,))
        existing = cursor.fetchone()
        conn.close()
        if not existing:
            return referral_id

@app.route('/update_mining', methods=['POST'])
def update_mining():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"}), 403

    data = request.json
    hashes = data.get('hashes')
    balance = data.get('balance')

    if hashes is None or balance is None:
        return jsonify({"error": "Invalid data"}), 400

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET mining_hashed=?, total_balance=? WHERE id=?", 
                   (hashes, balance, session['user_id']))
    conn.commit()
    conn.close()

    return jsonify({"message": "Mining updated successfully"}), 200

@app.route('/upgrade_level', methods=['POST'])
def upgrade_level():
    if 'user_id' not in session:
        return {'status': 'error', 'message': 'Not logged in'}, 403

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT total_balance, level FROM users WHERE id=?", (session['user_id'],))
    user = cursor.fetchone()

    if user is None:
        conn.close()
        return {'status': 'error', 'message': 'کاربر یافت نشد'}, 404

    if user[1] >= 7:
        conn.close()
        return {'status': 'error', 'message': 'حداکثر سطح قابل دستیابی ۷ است'}

    # هزینه‌های ارتقا به صورت دستی تعریف شده است
    upgrade_costs = [0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1]
    required_balance = upgrade_costs[user[1]]  # مقدار مورد نیاز برای ارتقا

    if user[0] < required_balance:
        conn.close()
        return {'status': 'error', 'message': 'موجودی کافی نیست'}

    new_level = user[1] + 1
    new_speed = 5 * new_level
    new_balance = user[0] - required_balance

    cursor.execute("UPDATE users SET level=?, mining_speed=?, total_balance=? WHERE id=?",
                   (new_level, new_speed, new_balance, session['user_id']))
    conn.commit()
    conn.close()

    return {
        'status': 'success',
        'message': f'سطح شما به {new_level} ارتقا یافت',
        'new_level': new_level,
        'new_speed': new_speed,
        'remaining_balance': new_balance
    }
    
    


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    referral_code = request.args.get('referral_link')

    referrer_id = None
    if referral_code and referral_code.isdigit():
        referrer_id = int(referral_code)
    print(f"Referrer ID from URL: {referrer_id}")  # چاپ مقدار دریافتی ریفرال

    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()

        # بررسی دوباره مقدار referral_link از فرم
        referral_link = request.form.get('referral_link')
        if referral_link and referral_link.isdigit():
            referrer_id = int(referral_link)  # تبدیل به int اگر عدد باشد
        print(f"Referral link from form: {referral_link}")  # چاپ لینک ریفرال

        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()

        try:
            cursor.execute("INSERT INTO users (first_name, last_name, email, password, referrer_id) VALUES (?, ?, ?, ?, ?)",
                           (first_name, last_name, email, password, referrer_id))
            conn.commit()

            user_id = cursor.lastrowid
            referral_link = str(user_id)
            cursor.execute("UPDATE users SET referral_link=? WHERE id=?", (referral_link, user_id))
            conn.commit()

            if referrer_id:
                cursor.execute("INSERT INTO referrals (user_id, referral_user_id) VALUES (?, ?)", (user_id, referrer_id))
                conn.commit()
                print(f"Referral saved: User {user_id} invited by {referrer_id}")

        except sqlite3.IntegrityError:
            flash('ایمیل قبلاً ثبت شده است.', 'danger')
            return redirect(url_for('register'))
        finally:
            conn.close()

        flash('ثبت‌نام موفقیت‌آمیز بود. لطفاً وارد شوید.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', referral_code=referral_code)

def get_user_count():
    """دریافت تعداد کل کاربران از پایگاه داده"""
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    conn.close()
    return user_count

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()

        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, password FROM users WHERE email=?", (email,))
        user = cursor.fetchone()
        conn.close()

        if user is None:
            flash('ایمیل نامعتبر است.')
        elif user[1] != password:
            flash('رمز عبور اشتباه است.')
        else:
            session['user_id'] = user[0]
            return redirect(url_for('dashboard'))

        return redirect(url_for('login'))

    # دریافت تعداد کاربران هنگام نمایش فرم لاگین
    user_count = get_user_count()
    return render_template('login.html', user_count=user_count)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # دریافت اطلاعات کاربر
    cursor.execute("SELECT first_name, last_name, email, referral_link, total_balance, mining_hashed, mining_speed, level FROM users WHERE id=?", (session['user_id'],))
    user = cursor.fetchone()

    # تعداد ارجاع‌ها
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (session['user_id'],))
    referral_count = cursor.fetchone()[0]

    # درآمد ارجاع
    cursor.execute("SELECT referral_rewards FROM users WHERE id=?", (session['user_id'],))  # استفاده از session['user_id']
    referral_income = cursor.fetchone()[0]  # مقدار درآمد ریفرال

    # دریافت ارجاع‌ها
    cursor.execute("SELECT user_id, referral_user_id FROM referrals WHERE user_id=?", (session['user_id'],))
    referrals = cursor.fetchall()
    print(f"Referrals for user {session['user_id']}: {referrals}")  # بررسی ریفرال‌ها در داشبورد

    conn.close()

    # بازگشت به قالب
    return render_template('dashboard.html', user=user, referral_count=referral_count, referral_income=referral_income, referrals=referrals)
    
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))
# اضافه کردن پاداش بعد از مشاهده تبلیغ
def get_db_connection():
    conn = sqlite3.connect("database.db")  # نام دیتابیس را بررسی کنید
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/add_reward", methods=["POST"])
def add_reward():
    user_id = session.get("user_id")  # بررسی ورود کاربر
    if not user_id:
        return jsonify({"error": "لطفاً وارد حساب خود شوید"}), 401

    reward_amount = 0.0001  # مقدار پاداش (قابل تغییر)

    conn = get_db_connection()
    conn.execute("UPDATE users SET total_balance = total_balance + ? WHERE id = ?", (reward_amount, user_id))
    conn.commit()
    conn.close()

    return jsonify({"message": "پاداش اضافه شد", "reward": reward_amount})

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

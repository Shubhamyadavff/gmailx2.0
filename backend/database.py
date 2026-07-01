import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'worker', -- 'worker' or 'admin'
            approved_balance REAL DEFAULT 0.0,
            pending_balance REAL DEFAULT 0.0,
            total_paid REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. Tasks Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            target_password TEXT NOT NULL,
            recovery_email TEXT NOT NULL,
            gmail_address TEXT,
            gmail_password TEXT,
            status TEXT DEFAULT 'assigned', -- 'assigned', 'submitted', 'verified', 'rejected'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            submitted_at TIMESTAMP,
            verified_at TIMESTAMP,
            error_message TEXT,
            FOREIGN KEY(worker_id) REFERENCES users(id)
        )
    ''')
    
    # 3. Withdrawals Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            payment_details TEXT NOT NULL,
            status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY(worker_id) REFERENCES users(id)
        )
    ''')
    
    # 4. Config Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payout_rate REAL DEFAULT 0.07,
            simulation_mode INTEGER DEFAULT 1, -- 1 = active, 0 = real telegram
            telegram_api_id TEXT,
            telegram_api_hash TEXT,
            telegram_phone TEXT,
            telegram_bot_username TEXT DEFAULT 'GmailFProBot',
            bot_routing_mode TEXT DEFAULT 'system'
        )
    ''')
    
    # Run migration check for bot_routing_mode
    try:
        cursor.execute("ALTER TABLE config ADD COLUMN bot_routing_mode TEXT DEFAULT 'system'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Run migration checks for tasks fields from bot reply
    for col, col_type in [("registration_id", "TEXT"), ("dob_month", "TEXT"), ("dob_day", "INTEGER"), ("dob_year", "INTEGER"), ("suggested_email", "TEXT")]:
        try:
            cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Create unique index on registration_id to guarantee database-level uniqueness for tasks
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_registration_id ON tasks(registration_id) WHERE registration_id IS NOT NULL")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    
    # 5. Telegram Bots Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS telegram_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_username TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'active', -- 'active' or 'inactive'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    
    # Seed default Admin user
    cursor.execute("SELECT id FROM users WHERE role = 'admin'")
    if not cursor.fetchone():
        from .auth import hash_password
        admin_hash = hash_password("J#8mZ!qW4vLpN^2xR&dT6yK")
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
            ("xr9_sysop_7kvault", admin_hash)
        )
        conn.commit()
        
    # Seed default config
    cursor.execute("SELECT id FROM config")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO config (payout_rate, simulation_mode, telegram_bot_username, bot_routing_mode) VALUES (?, ?, ?, ?)",
            (0.07, 1, 'GmailFProBot', 'system')
        )
        conn.commit()
        
    # Seed default bot if table is empty
    cursor.execute("SELECT id FROM telegram_bots")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO telegram_bots (bot_username, status) VALUES (?, ?)",
            ('GmailFProBot', 'active')
        )
        conn.commit()

    # Migration: Update existing config/bots from old default GmailFarmerBot to GmailFProBot
    cursor.execute("UPDATE config SET telegram_bot_username = 'GmailFProBot' WHERE telegram_bot_username = 'GmailFarmerBot'")
    cursor.execute("UPDATE telegram_bots SET bot_username = 'GmailFProBot' WHERE bot_username = 'GmailFarmerBot'")
    conn.commit()
        
    conn.close()

# USER HELPERS
def get_user_by_id(user_id: int):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return user

def get_user_by_username(username: str):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return user

def create_user(username: str, password_hash: str, role: str = 'worker'):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def update_worker_balances(worker_id: int, approved_delta: float = 0.0, pending_delta: float = 0.0, paid_delta: float = 0.0):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET approved_balance = approved_balance + ?,
            pending_balance = pending_balance + ?,
            total_paid = total_paid + ?
        WHERE id = ?
    ''', (approved_delta, pending_delta, paid_delta, worker_id))
    conn.commit()
    conn.close()

def get_all_workers():
    conn = get_db_connection()
    workers = conn.execute("SELECT id, username, role, approved_balance, pending_balance, total_paid, created_at FROM users WHERE role = 'worker'").fetchall()
    conn.close()
    return workers

# TASK HELPERS
def create_task(worker_id: int, first_name: str, last_name: str, target_password: str, recovery_email: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tasks (worker_id, first_name, last_name, target_password, recovery_email, status)
        VALUES (?, ?, ?, ?, ?, 'assigned')
    ''', (worker_id, first_name, last_name, target_password, recovery_email))
    conn.commit()
    task_id = cursor.lastrowid
    conn.close()
    return task_id

def get_active_task_for_worker(worker_id: int):
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM tasks WHERE worker_id = ? AND status IN ('assigned', 'submitted')", (worker_id,)).fetchone()
    conn.close()
    return task

def submit_task_credentials(task_id: int, gmail_address: str, gmail_password: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute('''
        UPDATE tasks
        SET gmail_address = ?, gmail_password = ?, status = 'submitted', submitted_at = ?
        WHERE id = ?
    ''', (gmail_address, gmail_password, now_str, task_id))
    conn.commit()
    conn.close()

def update_task_status(task_id: int, status: str, error_message: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    if status in ['verified', 'rejected']:
        cursor.execute('''
            UPDATE tasks
            SET status = ?, verified_at = ?, error_message = ?
            WHERE id = ?
        ''', (status, now_str, error_message, task_id))
    else:
        cursor.execute('''
            UPDATE tasks
            SET status = ?, error_message = ?
            WHERE id = ?
        ''', (status, error_message, task_id))
    conn.commit()
    conn.close()

def get_task_by_id(task_id: int):
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return task

def get_worker_task_history(worker_id: int):
    conn = get_db_connection()
    history = conn.execute("SELECT * FROM tasks WHERE worker_id = ? ORDER BY created_at DESC", (worker_id,)).fetchall()
    conn.close()
    return history

# WITHDRAWAL HELPERS
def create_withdrawal(worker_id: int, amount: float, payment_method: str, payment_details: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO withdrawals (worker_id, amount, payment_method, payment_details, status)
        VALUES (?, ?, ?, ?, 'pending')
    ''', (worker_id, amount, payment_method, payment_details))
    conn.commit()
    withdrawal_id = cursor.lastrowid
    conn.close()
    return withdrawal_id

def get_all_withdrawals():
    conn = get_db_connection()
    withdrawals = conn.execute('''
        SELECT w.*, u.username as worker_name 
        FROM withdrawals w
        JOIN users u ON w.worker_id = u.id
        ORDER BY w.created_at DESC
    ''').fetchall()
    conn.close()
    return withdrawals

def get_withdrawal_by_id(withdrawal_id: int):
    conn = get_db_connection()
    withdrawal = conn.execute("SELECT * FROM withdrawals WHERE id = ?", (withdrawal_id,)).fetchone()
    conn.close()
    return withdrawal

def update_withdrawal_status(withdrawal_id: int, status: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute('''
        UPDATE withdrawals
        SET status = ?, processed_at = ?
        WHERE id = ?
    ''', (status, now_str, withdrawal_id))
    conn.commit()
    conn.close()

def get_worker_withdrawals(worker_id: int):
    conn = get_db_connection()
    withdrawals = conn.execute("SELECT * FROM withdrawals WHERE worker_id = ? ORDER BY created_at DESC", (worker_id,)).fetchall()
    conn.close()
    return withdrawals

# CONFIG HELPERS
def get_config():
    conn = get_db_connection()
    config = conn.execute("SELECT * FROM config ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return config

def update_config(payout_rate: float, simulation_mode: int, telegram_api_id: str, telegram_api_hash: str, telegram_phone: str, telegram_bot_username: str, bot_routing_mode: str = 'system'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE config
        SET payout_rate = ?,
            simulation_mode = ?,
            telegram_api_id = ?,
            telegram_api_hash = ?,
            telegram_phone = ?,
            telegram_bot_username = ?,
            bot_routing_mode = ?
        WHERE id = 1
    ''', (payout_rate, simulation_mode, telegram_api_id, telegram_api_hash, telegram_phone, telegram_bot_username, bot_routing_mode))
    conn.commit()
    conn.close()

# TELEGRAM BOTS HELPERS
def get_all_bots():
    conn = get_db_connection()
    bots = conn.execute("SELECT * FROM telegram_bots ORDER BY id ASC").fetchall()
    conn.close()
    return bots

def get_active_bots():
    conn = get_db_connection()
    bots = conn.execute("SELECT * FROM telegram_bots WHERE status = 'active' ORDER BY id ASC").fetchall()
    conn.close()
    return bots

def add_bot(bot_username: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO telegram_bots (bot_username, status) VALUES (?, 'active')",
            (bot_username.strip(),)
        )
        conn.commit()
        bot_id = cursor.lastrowid
        conn.close()
        return bot_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def update_bot_status(bot_id: int, status: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE telegram_bots SET status = ? WHERE id = ?",
        (status, bot_id)
    )
    conn.commit()
    conn.close()

def delete_bot(bot_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM telegram_bots WHERE id = ?", (bot_id,))
    conn.commit()
    conn.close()

# TASK CYCLE HELPERS
def count_active_tasks_for_worker(worker_id: int):
    """Count how many assigned or submitted tasks a worker currently has."""
    conn = get_db_connection()
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE worker_id = ? AND status IN ('assigned', 'submitted')",
        (worker_id,)
    ).fetchone()['cnt']
    conn.close()
    return count

def get_submitted_tasks_for_worker(worker_id: int):
    """Get all submitted (pending verification) tasks for a worker."""
    conn = get_db_connection()
    tasks = conn.execute(
        "SELECT * FROM tasks WHERE worker_id = ? AND status = 'submitted' ORDER BY submitted_at ASC",
        (worker_id,)
    ).fetchall()
    conn.close()
    return tasks

# TASK ADMIN HELPERS
def get_all_tasks_admin():
    conn = get_db_connection()
    tasks = conn.execute('''
        SELECT t.*, u.username as worker_username
        FROM tasks t
        JOIN users u ON t.worker_id = u.id
        ORDER BY t.created_at DESC
    ''').fetchall()
    conn.close()
    return tasks

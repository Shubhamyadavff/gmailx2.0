import random
import string
from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional

from .database import (
    init_db, get_user_by_id, get_user_by_username, create_user,
    get_all_workers, get_active_task_for_worker, create_task,
    submit_task_credentials, get_task_by_id, update_task_status,
    get_worker_task_history, create_withdrawal, get_all_withdrawals,
    get_withdrawal_by_id, update_withdrawal_status, get_worker_withdrawals,
    get_config, update_config, update_worker_balances,
    get_all_bots, get_active_bots, add_bot, update_bot_status, delete_bot,
    get_all_tasks_admin, count_active_tasks_for_worker
)
from .auth import hash_password, verify_password, create_access_token, decode_access_token
from .telegram_manager import telegram_manager

# Initialize FastAPI App
app = FastAPI(title="Gmail Task Management System")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup DB initialization
@app.on_event("startup")
async def startup_event():
    init_db()
    # Try logging in Telegram on startup if credentials exist
    try:
        config = get_config()
        if config and config['simulation_mode'] == 0:
            client = await telegram_manager.get_client()
            if client:
                await client.connect()
                if await client.is_user_authorized():
                    await telegram_manager.start_message_listener()
    except Exception as e:
        print(f"Startup Telegram Auto-Login error: {e}")

# Security Schema
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token"
        )
    user = get_user_by_id(payload.get("user_id"))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    # Convert Row object to dict
    return dict(user)

def get_admin_user(current_user = Depends(get_current_user)):
    if current_user.get('role') != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Admin privileges required."
        )
    return current_user

# --- PYDANTIC SCHEMAS ---
class UserAuth(BaseModel):
    username: str
    password: str

class TaskSubmit(BaseModel):
    task_id: int
    gmail_address: str
    gmail_password: str

class WithdrawalRequest(BaseModel):
    amount: float
    payment_method: str
    payment_details: str

class ConfigUpdate(BaseModel):
    payout_rate: float
    simulation_mode: int
    telegram_api_id: Optional[str] = None
    telegram_api_hash: Optional[str] = None
    telegram_phone: Optional[str] = None
    telegram_bot_username: str
    bot_routing_mode: Optional[str] = 'system'

class TelegramConnect(BaseModel):
    phone: str
    api_id: str
    api_hash: str

class TelegramOTPVerify(BaseModel):
    code: str
    phone_code_hash: str
    password_2fa: Optional[str] = None

class BotCreate(BaseModel):
    bot_username: str

class BotStatusUpdate(BaseModel):
    status: str

class TaskReject(BaseModel):
    error_message: Optional[str] = None

class TaskImportRequest(BaseModel):
    raw_text: str

# --- AUTH ROUTES ---
@app.post("/api/auth/register")
def register(auth: UserAuth):
    username_cleaned = auth.username.strip().lower()
    if len(username_cleaned) < 3 or len(auth.password) < 6:
        raise HTTPException(status_code=400, detail="Username must be >= 3 chars, password >= 6 chars")
        
    pw_hash = hash_password(auth.password)
    user_id = create_user(username_cleaned, pw_hash, role='worker')
    if not user_id:
        raise HTTPException(status_code=400, detail="Username already exists")
        
    return {"status": "success", "message": "Registered successfully"}

@app.post("/api/auth/login")
def login(auth: UserAuth):
    username_cleaned = auth.username.strip().lower()
    user = get_user_by_username(username_cleaned)
    if not user or not verify_password(user['password_hash'], auth.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    token = create_access_token({"user_id": user['id'], "role": user['role']})
    return {"token": token, "role": user['role'], "username": user['username']}

@app.get("/api/auth/me")
def get_me(user = Depends(get_current_user)):
    user.pop('password_hash', None)
    return user

# --- WORKER TASK ROUTES ---
@app.get("/api/tasks/active")
def get_active_task(user = Depends(get_current_user)):
    task = get_active_task_for_worker(user['id'])
    if task:
        return dict(task)
    return None

@app.post("/api/tasks/request-new")
async def request_new_task_from_bot(user = Depends(get_current_user)):
    """Worker requests a new task from the Telegram bot."""
    # Check if worker already has an active task
    active_count = count_active_tasks_for_worker(user['id'])
    if active_count > 0:
        raise HTTPException(status_code=400, detail="You already have an active task. Complete it first.")
    
    config = get_config()
    if config and config['simulation_mode'] == 1:
        # In simulation mode, generate a random task
        new_task = telegram_manager._generate_random_task(user['id'])
        if new_task:
            return {"status": "success", "message": "New task assigned.", "task": dict(new_task)}
        raise HTTPException(status_code=500, detail="Failed to generate task.")
    else:
        # Request from Telegram bot
        try:
            new_task = await telegram_manager.request_new_task(user['id'])
            if new_task:
                return {"status": "success", "message": "New task received from bot.", "task": dict(new_task)}
            else:
                raise HTTPException(status_code=400, detail="Failed to retrieve task from bot: No response received.")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/tasks/import")
def import_task(req: TaskImportRequest, user = Depends(get_current_user)):
    import re
    from .database import get_db_connection
    text = req.raw_text
    
    # Extract values
    reg_id_match = re.search(r'(?:Registration ID|Reg ID):\s*([\w\-]+)', text, re.IGNORECASE)
    first_name_match = re.search(r'First name:\s*([^\n\r\-]+)', text, re.IGNORECASE)
    last_name_match = re.search(r'Last name:\s*([^\n\r\-]+)', text, re.IGNORECASE)
    
    # Date of Birth: Month: April | Day: 9 | Year: 1997
    dob_month_match = re.search(r'Month:\s*(\w+)', text, re.IGNORECASE)
    dob_day_match = re.search(r'Day:\s*(\d+)', text, re.IGNORECASE)
    dob_year_match = re.search(r'Year:\s*(\d+)', text, re.IGNORECASE)
    
    email_match = re.search(r'Email:\s*([\w\.-]+@[\w\.-]+)', text, re.IGNORECASE)
    pwd_match = re.search(r'Password:\s*([^\n\r\-]+)', text, re.IGNORECASE)
    
    reg_id = reg_id_match.group(1).strip() if reg_id_match else None
    first = first_name_match.group(1).strip() if first_name_match else None
    last = last_name_match.group(1).strip() if last_name_match else None
    
    dob_month = dob_month_match.group(1).strip() if dob_month_match else None
    dob_day = int(dob_day_match.group(1).strip()) if dob_day_match else None
    dob_year = int(dob_year_match.group(1).strip()) if dob_year_match else None
    
    email = email_match.group(1).strip() if email_match else None
    pwd = pwd_match.group(1).strip() if pwd_match else None
    
    if not (first and last and pwd):
        raise HTTPException(status_code=400, detail="Could not parse required fields (First name, Last name, Password) from text")
        
    # Check if there is an active task in 'assigned' status
    conn = get_db_connection()
    cursor = conn.cursor()
    
    active_task = cursor.execute(
        "SELECT * FROM tasks WHERE worker_id = ? AND status = 'assigned'",
        (user['id'],)
    ).fetchone()
    
    # Generate recovery email
    recovery = f"rec_{first.lower()}_{random.randint(1000, 9999)}@outlook.com"
    
    if active_task:
        # Update existing assigned task
        cursor.execute('''
            UPDATE tasks
            SET first_name = ?,
                last_name = ?,
                target_password = ?,
                recovery_email = ?,
                registration_id = ?,
                dob_month = ?,
                dob_day = ?,
                dob_year = ?,
                suggested_email = ?
            WHERE id = ?
        ''', (first, last, pwd, recovery, reg_id, dob_month, dob_day, dob_year, email, active_task['id']))
        task_id = active_task['id']
    else:
        # Create a new task
        cursor.execute('''
            INSERT INTO tasks (worker_id, first_name, last_name, target_password, recovery_email, registration_id, dob_month, dob_day, dob_year, suggested_email, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'assigned')
        ''', (user['id'], first, last, pwd, recovery, reg_id, dob_month, dob_day, dob_year, email))
        task_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    
    updated_task = get_task_by_id(task_id)
    return dict(updated_task)

@app.post("/api/tasks/submit")
async def submit_task(submit: TaskSubmit, background_tasks: BackgroundTasks, user = Depends(get_current_user)):
    task = get_task_by_id(submit.task_id)
    if not task or task['worker_id'] != user['id']:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task['status'] != 'assigned':
        raise HTTPException(status_code=400, detail="Task has already been submitted or completed")
        
    gmail_address = submit.gmail_address.strip().lower()
    if not gmail_address.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail="Must be a valid @gmail.com address")
        
    # Update status to submitted in DB
    submit_task_credentials(submit.task_id, gmail_address, submit.gmail_password.strip())
    
    # Run the integration pipeline in background thread
    background_tasks.add_task(telegram_manager.submit_gmail_task, submit.task_id)
    
    return {"status": "submitted", "message": "Task submitted. Verification pipeline initiated."}

@app.get("/api/tasks/history")
def get_task_history(user = Depends(get_current_user)):
    history = get_worker_task_history(user['id'])
    return [dict(t) for t in history]

# --- WITHDRAWAL ROUTES ---
@app.post("/api/withdrawals/request")
def request_withdrawal(req: WithdrawalRequest, user = Depends(get_current_user)):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be greater than zero")
        
    if user['approved_balance'] < req.amount:
        raise HTTPException(status_code=400, detail="Insufficient approved balance")
        
    # Subtract from approved balance and place in withdrawal pipeline
    update_worker_balances(user['id'], approved_delta=-req.amount)
    
    withdrawal_id = create_withdrawal(user['id'], req.amount, req.payment_method.strip(), req.payment_details.strip())
    return {"status": "success", "message": "Withdrawal request submitted successfully", "withdrawal_id": withdrawal_id}

@app.get("/api/withdrawals/history")
def get_my_withdrawals(user = Depends(get_current_user)):
    history = get_worker_withdrawals(user['id'])
    return [dict(w) for w in history]

# --- ADMIN ROUTES ---
@app.get("/api/admin/config")
def admin_get_config(admin = Depends(get_admin_user)):
    conf = get_config()
    return dict(conf)

@app.post("/api/admin/config")
def admin_update_config(conf: ConfigUpdate, admin = Depends(get_admin_user)):
    update_config(
        payout_rate=conf.payout_rate,
        simulation_mode=conf.simulation_mode,
        telegram_api_id=conf.telegram_api_id,
        telegram_api_hash=conf.telegram_api_hash,
        telegram_phone=conf.telegram_phone,
        telegram_bot_username=conf.telegram_bot_username,
        bot_routing_mode=conf.bot_routing_mode or 'system'
    )
    return {"status": "success", "message": "Configuration updated successfully"}

@app.get("/api/admin/workers")
def admin_get_workers(admin = Depends(get_admin_user)):
    workers = get_all_workers()
    return [dict(w) for w in workers]

@app.get("/api/admin/withdrawals")
def admin_get_withdrawals(admin = Depends(get_admin_user)):
    withdrawals = get_all_withdrawals()
    return [dict(w) for w in withdrawals]

# --- BOTS POOL ADMIN ROUTES ---
@app.get("/api/admin/bots")
def admin_get_bots(admin = Depends(get_admin_user)):
    bots = get_all_bots()
    return [dict(b) for b in bots]

@app.post("/api/admin/bots")
def admin_add_bot(bot: BotCreate, admin = Depends(get_admin_user)):
    username = bot.bot_username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Bot username cannot be empty")
    bot_id = add_bot(username)
    if not bot_id:
        raise HTTPException(status_code=400, detail="Bot already exists")
    return {"status": "success", "message": f"Bot @{username} added successfully", "id": bot_id}

@app.patch("/api/admin/bots/{id}/status")
def admin_update_bot_status(id: int, update: BotStatusUpdate, admin = Depends(get_admin_user)):
    if update.status not in ['active', 'inactive']:
        raise HTTPException(status_code=400, detail="Invalid status value. Must be 'active' or 'inactive'")
    update_bot_status(id, update.status)
    return {"status": "success", "message": "Bot status updated successfully"}

@app.delete("/api/admin/bots/{id}")
def admin_delete_bot(id: int, admin = Depends(get_admin_user)):
    delete_bot(id)
    return {"status": "success", "message": "Bot deleted successfully"}

# --- MANUAL GMAIL TASK VALIDATION ROUTES ---
@app.get("/api/admin/tasks")
def admin_get_tasks(admin = Depends(get_admin_user)):
    tasks = get_all_tasks_admin()
    return [dict(t) for t in tasks]

@app.post("/api/admin/tasks/{id}/approve")
async def admin_approve_task(id: int, background_tasks: BackgroundTasks, admin = Depends(get_admin_user)):
    task = get_task_by_id(id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task['status'] != 'submitted':
        raise HTTPException(status_code=400, detail="Task is not in 'submitted' status")
        
    config = get_config()
    payout = config['payout_rate'] or 0.07
    
    update_task_status(id, 'verified')
    update_worker_balances(task['worker_id'], approved_delta=payout, pending_delta=-payout)
    
    # Auto-cycle: assign a new task to the worker in background
    background_tasks.add_task(telegram_manager.auto_assign_new_task, task['worker_id'])
    
    return {"status": "success", "message": "Gmail account manually approved. New task will be auto-assigned."}

@app.post("/api/admin/tasks/{id}/reject")
async def admin_reject_task(id: int, reject: TaskReject, background_tasks: BackgroundTasks, admin = Depends(get_admin_user)):
    task = get_task_by_id(id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task['status'] != 'submitted':
        raise HTTPException(status_code=400, detail="Task is not in 'submitted' status")
        
    config = get_config()
    payout = config['payout_rate'] or 0.07
    
    reason = reject.error_message or "Manually declined by Admin"
    update_task_status(id, 'rejected', error_message=reason)
    update_worker_balances(task['worker_id'], pending_delta=-payout)
    
    # Auto-cycle: assign a new task to the worker in background
    background_tasks.add_task(telegram_manager.auto_assign_new_task, task['worker_id'])
    
    return {"status": "success", "message": "Gmail account manually rejected. New task will be auto-assigned."}

@app.post("/api/admin/tasks/{id}/send-to-bot")
async def admin_send_task_to_bot(id: int, background_tasks: BackgroundTasks, admin = Depends(get_admin_user)):
    """Re-send a submitted task to the Telegram bot for auto-verification."""
    task = get_task_by_id(id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task['status'] != 'submitted':
        raise HTTPException(status_code=400, detail="Task is not in 'submitted' status")
    
    background_tasks.add_task(telegram_manager.submit_gmail_task, id)
    return {"status": "success", "message": "Task re-sent to Telegram bot for verification."}

@app.post("/api/admin/withdrawals/{id}/approve")
def admin_approve_withdrawal(id: int, admin = Depends(get_admin_user)):
    withdrawal = get_withdrawal_by_id(id)
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal request not found")
        
    if withdrawal['status'] != 'pending':
        raise HTTPException(status_code=400, detail="Withdrawal request has already been finalized")
        
    # Update status to approved, and add to worker's total paid metric
    update_withdrawal_status(id, 'approved')
    update_worker_balances(withdrawal['worker_id'], paid_delta=withdrawal['amount'])
    
    return {"status": "success", "message": "Withdrawal request approved successfully"}

@app.post("/api/admin/withdrawals/{id}/reject")
def admin_reject_withdrawal(id: int, admin = Depends(get_admin_user)):
    withdrawal = get_withdrawal_by_id(id)
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal request not found")
        
    if withdrawal['status'] != 'pending':
        raise HTTPException(status_code=400, detail="Withdrawal request has already been finalized")
        
    # Reject request and refund balance back to user's approved balance
    update_withdrawal_status(id, 'rejected')
    update_worker_balances(withdrawal['worker_id'], approved_delta=withdrawal['amount'])
    
    return {"status": "success", "message": "Withdrawal request rejected and balance refunded"}

@app.get("/api/admin/telegram/status")
def admin_telegram_status(admin = Depends(get_admin_user)):
    return {
        "is_connected": telegram_manager.is_connected(),
        "phone": telegram_manager.phone
    }

@app.post("/api/admin/telegram/connect")
async def admin_telegram_connect(conn: TelegramConnect, admin = Depends(get_admin_user)):
    try:
        res = await telegram_manager.connect(conn.phone, conn.api_id, conn.api_hash)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Telegram connection request failed: {str(e)}")

@app.post("/api/admin/telegram/verify-otp")
async def admin_telegram_verify_otp(otp: TelegramOTPVerify, admin = Depends(get_admin_user)):
    try:
        res = await telegram_manager.verify_otp(otp.code, otp.phone_code_hash, otp.password_2fa)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OTP/2FA Verification failed: {str(e)}")

@app.post("/api/admin/telegram/disconnect")
async def admin_telegram_disconnect(admin = Depends(get_admin_user)):
    res = await telegram_manager.disconnect_telegram()
    return res

# Serve static frontend folder (Must be mounted last to allow REST routes precedence)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

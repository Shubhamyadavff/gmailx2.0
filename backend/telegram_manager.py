import asyncio
import os
import random
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from .database import (
    get_config, update_task_status, update_worker_balances,
    get_task_by_id, count_active_tasks_for_worker, create_task
)

# In-memory storage for active client connections and login state
class TelegramManager:
    def __init__(self):
        self.client = None
        self.phone = None
        self.phone_code_hash = None
        self.active_tasks = {} # maps task_id to asyncio tasks for simulation
        self.request_lock = asyncio.Lock()

    def is_connected(self):
        config = get_config()
        if not config:
            return False
            
        # In simulation mode, we are always considered "connected"
        if config['simulation_mode'] == 1:
            return True
            
        return self.client is not None and self.client.is_connected()

    async def send_and_wait_for_reply(self, bot_username: str, send_action, timeout: float = 12.0):
        """
        Executes a send action (e.g. sending a message or clicking a button)
        and waits for the next incoming message from the bot.
        """
        loop = asyncio.get_running_loop()
        reply_future = loop.create_future()

        # Temporary handler to capture the next incoming message
        @self.client.on(events.NewMessage(incoming=True, from_users=bot_username))
        async def temp_handler(event):
            if not reply_future.done():
                reply_future.set_result(event.message)

        try:
            # Execute the send action
            await send_action()
            # Wait for response with timeout
            reply_msg = await asyncio.wait_for(reply_future, timeout=timeout)
            return reply_msg
        finally:
            try:
                self.client.remove_event_handler(temp_handler)
            except Exception:
                pass

    async def get_client(self):
        if self.client:
            return self.client
            
        config = get_config()
        if not config or not config['telegram_api_id'] or not config['telegram_api_hash']:
            return None
            
        session_path = os.path.join(os.path.dirname(__file__), 'admin_session')
        
        # Initialize client
        self.client = TelegramClient(
            session_path,
            int(config['telegram_api_id']),
            config['telegram_api_hash']
        )
        return self.client

    async def connect(self, phone: str, api_id: str, api_hash: str):
        config = get_config()
        
        # If in simulation mode, mock the connection
        if config['simulation_mode'] == 1:
            self.phone = phone
            return {"status": "otp_required", "phone_code_hash": "mock_hash"}

        # Real connection
        session_path = os.path.join(os.path.dirname(__file__), 'admin_session')
        
        # Clean up old client if any
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
            
        try:
            self.client = TelegramClient(session_path, int(api_id), api_hash)
            await self.client.connect()
            
            # Send code request
            sent_code = await self.client.send_code_request(phone)
            self.phone = phone
            self.phone_code_hash = sent_code.phone_code_hash
            
            return {
                "status": "otp_required",
                "phone_code_hash": sent_code.phone_code_hash
            }
        except Exception as e:
            if self.client:
                await self.client.disconnect()
                self.client = None
            raise e

    async def verify_otp(self, code: str, phone_code_hash: str, password_2fa: str = None):
        config = get_config()
        
        if config['simulation_mode'] == 1:
            if code == "00000":
                raise ValueError("Simulated OTP validation failed (invalid code 00000)")
            return {"status": "success", "message": "Simulated Telegram linked successfully!"}
            
        if not self.client:
            raise ValueError("No active connection request found. Please connect first.")
            
        try:
            # Try to sign in
            await self.client.sign_in(
                self.phone,
                code,
                phone_code_hash=phone_code_hash
            )
            # Setup background message listener for bot
            await self.start_message_listener()
            return {"status": "success", "message": "Telegram account linked successfully!"}
            
        except SessionPasswordNeededError:
            if password_2fa:
                await self.client.sign_in(password=password_2fa)
                await self.start_message_listener()
                return {"status": "success", "message": "Telegram account linked with 2FA successfully!"}
            else:
                return {
                    "status": "2fa_required",
                    "message": "Two-factor authentication password is required."
                }
        except Exception as e:
            raise e

    async def disconnect_telegram(self):
        if self.client:
            await self.client.disconnect()
            self.client = None
        self.phone = None
        self.phone_code_hash = None
        return {"status": "disconnected"}

    async def start_message_listener(self):
        """Starts listening for messages from the target Telegram bot in real mode."""
        if not self.client or not self.client.is_connected():
            return
            
        @self.client.on(events.NewMessage(incoming=True))
        async def handler(event):
            # Check if the sender is in our active bots pool
            sender = await event.get_sender()
            if not sender or not sender.username:
                return
                
            from .database import get_active_bots, get_config
            config = get_config()
            routing_mode = dict(config).get('bot_routing_mode', 'system') if config else 'system'
            
            active_usernames = set()
            if routing_mode == 'pool':
                active_bots = get_active_bots()
                active_usernames = {bot['bot_username'].lower().strip().replace('@', '') for bot in active_bots}
                
            # Fallback to the main config bot if in system mode or pool is empty
            if not active_usernames or routing_mode == 'system':
                if config and config['telegram_bot_username']:
                    active_usernames.add(config['telegram_bot_username'].lower().strip().replace('@', ''))
                
            sender_username = sender.username.lower().strip()
            if sender_username not in active_usernames:
                return
                
            text = event.message.message.lower()
            # Try to find corresponding submitted task
            gmail_address = None
            import re
            emails = re.findall(r'[\w\.-]+@gmail\.com', text)
            if emails:
                gmail_address = emails[0]
                
            # Query db for matching task
            from .database import get_db_connection
            conn = get_db_connection()
            if gmail_address:
                task = conn.execute(
                    "SELECT * FROM tasks WHERE gmail_address = ? AND status = 'submitted'",
                    (gmail_address,)
                ).fetchone()
            else:
                # Fallback: get the oldest pending submitted task
                task = conn.execute(
                    "SELECT * FROM tasks WHERE status = 'submitted' ORDER BY submitted_at ASC LIMIT 1"
                ).fetchone()
            conn.close()
            
            if not task:
                return # No active task matches
                
            task_id = task['id']
            worker_id = task['worker_id']
            payout = config['payout_rate'] or 0.07
            
            # Match validation keywords
            success_keywords = ['success', 'approved', 'verified', 'valid', 'active', 'good', 'added', 'done', 'created']
            failure_keywords = ['fail', 'invalid', 'rejected', 'error', 'wrong', 'exist', 'used', 'bad', 'block']
            
            is_success = any(kw in text for kw in success_keywords)
            is_failure = any(kw in text for kw in failure_keywords)
            
            if is_success:
                update_task_status(task_id, 'verified')
                update_worker_balances(worker_id, approved_delta=payout, pending_delta=-payout)
                # Auto-cycle: fetch next task from bot for this worker
                asyncio.create_task(self.auto_assign_new_task(worker_id))
            elif is_failure:
                update_task_status(task_id, 'rejected', error_message=event.message.message)
                update_worker_balances(worker_id, pending_delta=-payout)
                # Auto-cycle: fetch next task from bot for this worker
                asyncio.create_task(self.auto_assign_new_task(worker_id))

    async def auto_assign_new_task(self, worker_id: int):
        """Auto-cycle: After task completion, fetch and assign next task from bot."""
        try:
            # Small delay to allow UI to update
            await asyncio.sleep(2)
            
            # Check if worker already has an active task
            active_count = count_active_tasks_for_worker(worker_id)
            if active_count > 0:
                print(f"[AutoCycle] Worker {worker_id} already has an active task, skipping auto-assign.")
                return None
            
            config = get_config()
            
            if config and config['simulation_mode'] == 1:
                # In simulation mode, generate a random task
                return self._generate_random_task(worker_id)
            else:
                # In real mode, request from Telegram bot
                new_task = await self.request_new_task(worker_id)
                if new_task:
                    print(f"[AutoCycle] New task #{dict(new_task)['id']} assigned to worker {worker_id} from bot.")
                    return new_task
                else:
                    print(f"[AutoCycle] Bot didn't respond, no task assigned to worker {worker_id}.")
                    return None
        except Exception as e:
            print(f"[AutoCycle] Error auto-assigning task: {e}")
            return None

    def _generate_random_task(self, worker_id: int):
        """Generate a random task for a worker (simulation fallback)."""
        import string
        
        first_names = ["John", "James", "David", "Robert", "Michael", "William", "Richard", "Thomas", "Charles", "Joseph", "Emma", "Olivia", "Ava", "Isabella", "Sophia", "Charlotte", "Mia", "Amelia", "Harper", "Evelyn"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"]
        
        first = random.choice(first_names)
        last = random.choice(last_names)
        
        random_str = ''.join(random.choices(string.ascii_lowercase, k=4))
        digits = ''.join(random.choices(string.digits, k=3))
        target_pwd = f"{first}{random_str.capitalize()}{digits}!"
        
        rec_rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        recovery = f"rec_{first.lower()}_{rec_rand}@outlook.com"
        
        reg_id = f"G{random.randint(10000000, 99999999)}"
        dob_month = random.choice(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])
        dob_day = random.randint(1, 28)
        dob_year = random.randint(1985, 2002)
        suggested_email = f"{first.lower()}.{last.lower()}{random.randint(10, 99)}@gmail.com"
        
        from .database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tasks (worker_id, first_name, last_name, target_password, recovery_email, registration_id, dob_month, dob_day, dob_year, suggested_email, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'assigned')
        ''', (worker_id, first, last, target_pwd, recovery, reg_id, dob_month, dob_day, dob_year, suggested_email))
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return get_task_by_id(task_id)

    async def submit_gmail_task(self, task_id: int):
        """Routes task credentials. In simulation mode, runs a mock validation timer."""
        config = get_config()
        task = get_task_by_id(task_id)
        if not task:
            return
            
        worker_id = task['worker_id']
        payout = config['payout_rate'] or 0.07
        
        # 1. Update worker pending balance (on submission)
        update_worker_balances(worker_id, pending_delta=payout)
        
        # 2. Run verification pipeline
        if config['simulation_mode'] == 1:
            # Run simulation in the background
            sim_task = asyncio.create_task(self._run_simulation_task(task_id, worker_id, payout))
            self.active_tasks[task_id] = sim_task
        else:
            # Send message to Telegram bot
            if not self.client or not self.client.is_connected():
                # If Telegram is offline in real mode, auto-reject
                update_task_status(task_id, 'rejected', error_message="Telegram account not linked/connected.")
                update_worker_balances(worker_id, pending_delta=-payout)
                return
                
            from .database import get_active_bots
            routing_mode = dict(config).get('bot_routing_mode', 'system') if config else 'system'
            
            bot_username = None
            if routing_mode == 'pool':
                active_bots = get_active_bots()
                if active_bots:
                    # Choose one of the active pool bots randomly
                    bot_username = random.choice(active_bots)['bot_username']
                    
            if not bot_username:
                bot_username = config['telegram_bot_username'] or 'GmailFProBot'
                
            bot_username = bot_username.strip().replace('@', '')
            message_text = f"New Account Submission:\nEmail: {task['gmail_address']}\nPassword: {task['gmail_password']}\nRecovery: {task['recovery_email']}"
            try:
                await self.client.send_message(bot_username, message_text)
            except Exception as e:
                update_task_status(task_id, 'rejected', error_message=f"Failed to route message to bot: {str(e)}")
                update_worker_balances(worker_id, pending_delta=-payout)

    async def _run_simulation_task(self, task_id: int, worker_id: int, payout: float):
        # Simulate bot latency
        await asyncio.sleep(random.randint(6, 12))
        
        # 85% success chance
        is_success = random.random() < 0.85
        
        if is_success:
            update_task_status(task_id, 'verified')
            update_worker_balances(worker_id, approved_delta=payout, pending_delta=-payout)
        else:
            errors = [
                "Bot rejected: Recovery email verification requested.",
                "Bot rejected: Phone number required for SMS verification.",
                "Bot rejected: Gmail account has been suspended.",
                "Bot rejected: Invalid credentials or incorrect password format."
            ]
            update_task_status(task_id, 'rejected', error_message=random.choice(errors))
            update_worker_balances(worker_id, pending_delta=-payout)
            
        # Clean up mapping
        self.active_tasks.pop(task_id, None)
        
        # Auto-cycle: generate a new task for the worker after completion
        await self.auto_assign_new_task(worker_id)

    async def request_new_task(self, worker_id: int):
        """Sends /start to target bot, clicks 'New Account', clicks 'New Task', then parses response."""
        config = get_config()
        if not config or config['simulation_mode'] == 1:
            return None
            
        if not self.client or not self.client.is_connected():
            raise ValueError("Telegram client is not connected. Please link your Telegram account in the Admin Panel.")
            
        from .database import get_active_bots
        routing_mode = dict(config).get('bot_routing_mode', 'system') if config else 'system'
        
        bot_username = None
        if routing_mode == 'pool':
            active_bots = get_active_bots()
            if active_bots:
                bot_username = random.choice(active_bots)['bot_username']
                
        if not bot_username:
            bot_username = config['telegram_bot_username'] or 'GmailFProBot'
            
        bot_username = bot_username.strip().replace('@', '')
        
        # Use request_lock to prevent concurrent requests from mixing bot replies
        async with self.request_lock:
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    # 1. Send /start and wait for reply
                    try:
                        reply = await self.send_and_wait_for_reply(
                            bot_username,
                            lambda: self.client.send_message(bot_username, "/start"),
                            timeout=8.0
                        )
                    except asyncio.TimeoutError:
                        if attempt == max_attempts:
                            raise ValueError("Timeout waiting for bot response to /start command.")
                        print(f"[TelegramManager] Attempt {attempt} failed on /start timeout. Retrying...")
                        await asyncio.sleep(1)
                        continue

                    # Wait 3 seconds after /start command reply before clicking New Account
                    await asyncio.sleep(3)

                    # Helper to find and click button
                    async def click_button_with_fallback(current_reply, queries, text_fallback):
                        clicked = False
                        if current_reply and hasattr(current_reply, 'buttons') and current_reply.buttons:
                            for row in current_reply.buttons:
                                for btn in row:
                                    btn_text = btn.text or ""
                                    if any(q.lower() in btn_text.lower() for q in queries):
                                        try:
                                            await btn.click()
                                            clicked = True
                                            break
                                        except Exception as e:
                                            print(f"Error clicking button '{btn_text}': {e}")
                                if clicked:
                                    break
                        if not clicked:
                            # Fallback to sending text message
                            await self.client.send_message(bot_username, text_fallback)

                    # 2. Click "New Account" and wait for reply
                    try:
                        reply = await self.send_and_wait_for_reply(
                            bot_username,
                            lambda: click_button_with_fallback(reply, ["new account", "account", "register"], "New Account"),
                            timeout=8.0
                        )
                    except asyncio.TimeoutError:
                        if attempt == max_attempts:
                            raise ValueError("Timeout waiting for bot response after requesting New Account.")
                        print(f"[TelegramManager] Attempt {attempt} failed on New Account timeout. Retrying...")
                        await asyncio.sleep(1)
                        continue

                    # Wait 3 seconds after New Account reply before clicking New Task
                    await asyncio.sleep(3)

                    # 3. Click "New Task" and wait for reply containing details
                    try:
                        reply = await self.send_and_wait_for_reply(
                            bot_username,
                            lambda: click_button_with_fallback(reply, ["new task", "task", "get task"], "New Task"),
                            timeout=8.0
                        )
                    except asyncio.TimeoutError:
                        if attempt == max_attempts:
                            raise ValueError("Timeout waiting for bot response after requesting New Task.")
                        print(f"[TelegramManager] Attempt {attempt} failed on New Task timeout. Retrying...")
                        await asyncio.sleep(1)
                        continue

                    if not reply or not reply.message:
                        if attempt == max_attempts:
                            raise ValueError("Empty response received from task bot.")
                        print(f"[TelegramManager] Attempt {attempt} returned empty response. Retrying...")
                        await asyncio.sleep(1)
                        continue

                    text = reply.message

                    # 4. Parse the task details
                    import re
                    reg_id_match = re.search(r'(?:Registration ID|Reg ID|Task ID|ID):\s*([\w\-]+)', text, re.IGNORECASE)
                    first_name_match = re.search(r'(?:First name|First):\s*([^\n\r\-]+)', text, re.IGNORECASE)
                    last_name_match = re.search(r'(?:Last name|Last):\s*([^\n\r\-]+)', text, re.IGNORECASE)
                    
                    dob_month_match = re.search(r'Month:\s*(\w+)', text, re.IGNORECASE)
                    dob_day_match = re.search(r'Day:\s*(\d+)', text, re.IGNORECASE)
                    dob_year_match = re.search(r'Year:\s*(\d+)', text, re.IGNORECASE)
                    
                    suggested_email_match = re.search(r'(?:Suggested Email|Suggested|Email):\s*([\w\.-]+@[\w\.-]+)', text, re.IGNORECASE)
                    recovery_email_match = re.search(r'(?:Recovery Email|Recovery):\s*([\w\.-]+@[\w\.-]+)', text, re.IGNORECASE)
                    pwd_match = re.search(r'(?:Password|Pass|Pwd|Target Password):\s*([^\n\r\-]+)', text, re.IGNORECASE)

                    # If it's not a valid task format, raise the raw reply message as an error
                    if not first_name_match or not pwd_match:
                        if attempt == max_attempts:
                            raise ValueError(f"Bot response: {text}")
                        print(f"[TelegramManager] Attempt {attempt} parsed invalid task layout. Retrying...")
                        await asyncio.sleep(1)
                        continue

                    reg_id = reg_id_match.group(1).strip() if reg_id_match else f"G{random.randint(10000000, 99999999)}"
                    first = first_name_match.group(1).strip() if first_name_match else "James"
                    last = last_name_match.group(1).strip() if last_name_match else "Hudman"
                    
                    dob_month = dob_month_match.group(1).strip() if dob_month_match else "April"
                    dob_day = int(dob_day_match.group(1).strip()) if dob_day_match else 9
                    dob_year = int(dob_year_match.group(1).strip()) if dob_year_match else 1997
                    
                    email = suggested_email_match.group(1).strip() if suggested_email_match else f"rec_{first.lower()}_{random.randint(10, 99)}@gmail.com"
                    pwd = pwd_match.group(1).strip() if pwd_match else "JqbdvMQ3vFNT"
                    
                    recovery = recovery_email_match.group(1).strip() if recovery_email_match else f"rec_{first.lower()}_{random.randint(1000, 9999)}@outlook.com"
                    
                    # 5. Check if the task ID (registration_id) is unique in DB
                    from .database import get_db_connection, get_task_by_id
                    conn = get_db_connection()
                    existing = conn.execute("SELECT id FROM tasks WHERE registration_id = ?", (reg_id,)).fetchone()
                    if existing:
                        conn.close()
                        if attempt == max_attempts:
                            raise ValueError(f"Duplicate task received: Task ID {reg_id} is already assigned in system.")
                        print(f"[TelegramManager] Attempt {attempt} received duplicate Task ID {reg_id}. Retrying...")
                        await asyncio.sleep(1)
                        continue

                    # 6. Save new task and assign to worker
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO tasks (worker_id, first_name, last_name, target_password, recovery_email, registration_id, dob_month, dob_day, dob_year, suggested_email, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'assigned')
                    ''', (worker_id, first, last, pwd, recovery, reg_id, dob_month, dob_day, dob_year, email))
                    task_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    
                    return get_task_by_id(task_id)
                except Exception as e:
                    if attempt == max_attempts:
                        raise e
                    print(f"[TelegramManager] Attempt {attempt} failed with exception: {e}. Retrying...")
                    await asyncio.sleep(1)

# Global Manager Instance
telegram_manager = TelegramManager()

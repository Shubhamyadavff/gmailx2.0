# Gmail Task Management Board & Telegram Integration

An automated full-stack platform designed to manage Gmail account creation tasks. It routes instructions and credential submissions securely through an admin Telegram account (using MTProto via Telethon) to interact with task bots like `Gmail Farmer Bot`, and distributes payouts to workers through a sleek, glassmorphic web dashboard.

---

## Features

### 1. Worker Console
- **Work Station**: Dynamic card showing assigned tasks (First Name, Last Name, Target Password, Recovery Email) with quick-copy buttons.
- **Verification Flow**: Input fields for submitted Gmail credentials, routing details to the Telegram bot automatically.
- **Wallet & Balance Tracking**: Displays Approved Balance (ready for withdrawal), Pending Balance (awaiting validation), and Total Paid out.
- **Withdrawal Requests**: Workers can request payouts directly, specifying payment methods (USDT, Paypal, UPI, local bank).

### 2. Admin Control Panel
- **Telegram Account Linker**: Interactive OTP security connection sequence using your `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org).
- **Simulation Mode Toggle**: Run and demo the entire project workflow immediately without any Telegram credentials or real account verification.
- **Configurable Payouts**: Define the worker payout amount per account (e.g., $0.05 to $0.09).
- **Worker Management**: Real-time listing of all registered workers, registration dates, and earnings summaries.
- **Payout Clearing Center**: Process and approve worker withdrawal requests, automatically calculating wallet adjustments.

---

## Repository Structure

```
├── backend/
│   ├── main.py              # FastAPI Web Router and static routes
│   ├── auth.py              # secure password hashing & JWT token validation
│   ├── database.py          # SQLite schema and helpers
│   ├── telegram_manager.py  # Telethon MTProto connection manager and bot message parsing
│   └── requirements.txt     # Python backend dependencies
├── frontend/
│   ├── index.html           # SPA structure containing Worker and Admin panels
│   ├── style.css            # Custom glassmorphic CSS styling
│   └── app.js               # Frontend controller logic, API calling & polling
├── .gitignore               # Excludes virtual environments, DB, and Telegram sessions
└── README.md                # Project documentation
```

---

## Getting Started

### Prerequisites
- Python 3.8+ (This project was verified on Python 3.14)
- A Telegram account with API credentials from [my.telegram.org](https://my.telegram.org) (optional, if running in real Telegram mode).

### Local Installation

1. **Clone the Repository**:
   ```bash
   git clone <your-repository-url>
   cd <repository-directory>
   ```

2. **Initialize a Virtual Environment**:
   ```bash
   python -m venv .venv
   ```

3. **Activate Virtual Environment**:
   - **Windows**:
     ```powershell
     .venv\Scripts\activate
     ```
   - **macOS/Linux**:
     ```bash
     source .venv/bin/activate
     ```

4. **Install Dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```

5. **Run the Server**:
   ```bash
   python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
   ```

6. **Access the Application**:
   Open `http://127.0.0.1:8000` in your web browser.

---

## Default Credentials

The database will be automatically seeded at startup with a default Admin account:
- **Username**: `admin`
- **Password**: `admin123`

*Note: For security, immediately change this password or add customized security checks before hosting in production.*

---

## GitHub Deployment & Security Warnings

> [!WARNING]
> **Keep Credentials Safe**:
> 1. Never delete the entries in `.gitignore`. The file `backend/database.db` and files starting with `backend/admin_session` contain sensitive credentials, user passwords, and active Telegram login sessions. If committed, anyone who views the repository can access your Telegram account.
> 2. Do not hardcode API hashes or security secrets.

### Uploading to GitHub

To publish this project to your own GitHub account:
1. Initialize the git repository:
   ```bash
   git init
   ```
2. Stage and commit files:
   ```bash
   git add .
   ```
   *Verify that `.venv`, `database.db`, and `admin_session` files are NOT staged using `git status`.*
3. Commit changes:
   ```bash
   git commit -m "feat: initial commit for gmail farmer dashboard"
   ```
4. Create a repository on GitHub, then link and push:
   ```bash
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
   git push -u origin main
   ```

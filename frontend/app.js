// State Management
let apiToken = localStorage.getItem('gmail_farmer_token') || '';
let currentUser = null;
let activeTask = null;
let isRegistering = false;
let pollingInterval = null;
let phoneCodeHash = null;

// API Base Endpoints
const API_URL = window.location.origin;

// Helper Headers
function getHeaders() {
    const headers = {
        'Content-Type': 'application/json'
    };
    if (apiToken) {
        headers['Authorization'] = `Bearer ${apiToken}`;
    }
    return headers;
}

// ================= TOAST NOTIFICATION SYSTEM =================
function showToast(title, message, type = 'info', duration = 5000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const iconMap = {
        success: 'check-circle',
        error: 'alert-circle',
        info: 'info',
        warning: 'alert-triangle'
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.style.position = 'relative';
    toast.innerHTML = `
        <i data-lucide="${iconMap[type] || 'info'}" class="toast-icon"></i>
        <div class="toast-body">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">
            <i data-lucide="x" style="width:16px;height:16px;"></i>
        </button>
        <div class="toast-progress" style="animation-duration: ${duration}ms;"></div>
    `;

    container.appendChild(toast);
    lucide.createIcons();

    // Auto-remove after duration
    const timer = setTimeout(() => {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 400);
    }, duration);

    // Allow manual close to cancel timer
    toast.querySelector('.toast-close').addEventListener('click', () => {
        clearTimeout(timer);
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 400);
    });
}

// Global Clipboard Copy Utility
window.copyField = function(inputId, btnElement) {
    const input = document.getElementById(inputId);
    if (!input || !input.value || input.value === '...') return;
    
    input.select();
    input.setSelectionRange(0, 99999);
    navigator.clipboard.writeText(input.value);
    
    // Animate copy feedback
    const originalContent = btnElement.innerHTML;
    btnElement.innerHTML = '<i data-lucide="check"></i>';
    btnElement.classList.add('copied');
    lucide.createIcons();
    
    setTimeout(() => {
        btnElement.innerHTML = originalContent;
        btnElement.classList.remove('copied');
        lucide.createIcons();
    }, 1800);
};

// Open and Close Modals
window.openModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('hidden');
        if (modalId === 'withdraw-modal' && currentUser) {
            document.getElementById('modal-approved-balance').textContent = currentUser.approved_balance.toFixed(2);
        }
    }
};

window.closeModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('hidden');
    }
};

// Initializer
document.addEventListener('DOMContentLoaded', () => {
    initApp();
    setupEventListeners();
});

// App Router / Initializer
async function initApp() {
    lucide.createIcons();
    if (apiToken) {
        const success = await fetchCurrentUser();
        if (success) {
            if (currentUser.role === 'admin') {
                showTab('admin');
            } else {
                showTab('worker');
            }
            initDashboard();
        } else {
            logout();
        }
    } else {
        showTab('auth');
    }
}

function showTab(tabName) {
    document.getElementById('auth-container').classList.add('hidden');
    document.getElementById('worker-dashboard').classList.add('hidden');
    document.getElementById('admin-dashboard').classList.add('hidden');
    
    if (tabName === 'auth') {
        document.getElementById('auth-container').classList.remove('hidden');
    } else if (tabName === 'worker') {
        document.getElementById('worker-dashboard').classList.remove('hidden');
    } else if (tabName === 'admin') {
        document.getElementById('admin-dashboard').classList.remove('hidden');
    }
    lucide.createIcons();
}

// Setup Dashboard components
function initDashboard() {
    if (currentUser.role === 'admin') {
        document.getElementById('nav-admin-btn').classList.remove('hidden');
        loadAdminData();
    } else {
        document.getElementById('nav-admin-btn').classList.add('hidden');
    }
    
    if (document.getElementById('worker-dashboard').classList.contains('hidden') === false) {
        document.getElementById('worker-username').textContent = currentUser.username;
        updateBalanceUI();
        loadActiveTask();
        loadWorkerHistory();
    }
}

// Update balance figures on Worker Console
function updateBalanceUI() {
    document.getElementById('bal-approved').textContent = currentUser.approved_balance.toFixed(2);
    document.getElementById('bal-pending').textContent = currentUser.pending_balance.toFixed(2);
    document.getElementById('bal-paid').textContent = currentUser.total_paid.toFixed(2);
}

// Fetch Current User Profile
async function fetchCurrentUser() {
    try {
        const res = await fetch(`${API_URL}/api/auth/me`, {
            headers: getHeaders()
        });
        if (res.status === 200) {
            currentUser = await res.json();
            return true;
        }
        return false;
    } catch (e) {
        console.error(e);
        return false;
    }
}

// Load Assigned Task Info
async function loadActiveTask() {
    // Show Loading
    document.getElementById('task-loader').classList.remove('hidden');
    document.getElementById('task-details-area').classList.add('hidden');
    document.getElementById('task-submit-form').classList.add('hidden');
    document.getElementById('no-task-area').classList.add('hidden');
    hideAutoCycleTracker();
    
    try {
        const res = await fetch(`${API_URL}/api/tasks/active`, {
            headers: getHeaders()
        });
        const task = await res.json();
        activeTask = task;
        
        document.getElementById('task-loader').classList.add('hidden');
        
        if (!task || Object.keys(task).length === 0) {
            document.getElementById('no-task-area').classList.remove('hidden');
            document.getElementById('btn-request-bot-task').classList.add('hidden');
            hidePipelineTracker();
            return;
        }
        
        document.getElementById('task-details-area').classList.remove('hidden');
        document.getElementById('task-submit-form').classList.remove('hidden');
        document.getElementById('btn-request-bot-task').classList.remove('hidden');
        
        renderActiveTaskData(task);
        
        // Check current status of the task
        if (task.status === 'submitted') {
            showPipelineTracker("Verifying submission...", "Sent for validation to Bot. Polling response...");
            startStatusPolling(task.id);
        } else {
            hidePipelineTracker();
        }
    } catch (e) {
        console.error(e);
        document.getElementById('task-loader').classList.add('hidden');
        document.getElementById('no-task-area').classList.remove('hidden');
    }
}

function renderActiveTaskData(task) {
    document.getElementById('task-first-name').value = task.first_name || '';
    document.getElementById('task-last-name').value = task.last_name || '';
    document.getElementById('task-password').value = task.target_password || '';
    document.getElementById('task-recovery').value = task.recovery_email || '';
    
    document.getElementById('task-reg-id').value = task.registration_id || 'N/A';
    document.getElementById('task-suggested-email').value = task.suggested_email || 'N/A';
    
    let dobStr = 'N/A';
    if (task.dob_month || task.dob_day || task.dob_year) {
        dobStr = `${task.dob_month || ''} ${task.dob_day || ''}, ${task.dob_year || ''}`.trim();
    }
    document.getElementById('task-dob').value = dobStr;
    
    document.getElementById('submit-task-id').value = task.id;
    
    // Auto-fill submission form
    if (task.suggested_email) {
        document.getElementById('gmail-address').value = task.suggested_email;
    } else {
        document.getElementById('gmail-address').value = '';
    }
    if (task.target_password) {
        document.getElementById('gmail-password').value = task.target_password;
    } else {
        document.getElementById('gmail-password').value = '';
    }
}

async function handleTaskImport() {
    const pasteArea = document.getElementById('task-paste-area');
    const text = pasteArea.value.trim();
    if (!text) {
        showToast("Missing Input", "Please paste the Telegram bot message first.", "warning");
        return;
    }
    
    const btn = document.getElementById('btn-parse-task');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner" style="width:14px; height:14px; border-width:2px; display:inline-block; margin-right:5px; vertical-align:middle;"></div> Parsing...';
    
    try {
        const res = await fetch(`${API_URL}/api/tasks/import`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ raw_text: text })
        });
        
        if (res.status === 200) {
            const updatedTask = await res.json();
            pasteArea.value = '';
            btn.innerHTML = '<i data-lucide="check"></i> Imported!';
            btn.style.backgroundColor = 'var(--success-green)';
            btn.style.color = '#fff';
            lucide.createIcons();
            
            showToast("Task Imported", "Bot task message parsed and loaded successfully.", "success");
            
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = originalText;
                btn.style.backgroundColor = '';
                btn.style.color = '';
                lucide.createIcons();
            }, 2000);
            
            // Load the updated active task immediately
            activeTask = updatedTask;
            renderActiveTaskData(updatedTask);
        } else {
            const err = await res.json();
            showToast("Parse Failed", err.detail || "Verify the message format", "error");
            btn.disabled = false;
            btn.innerHTML = originalText;
            lucide.createIcons();
        }
    } catch (e) {
        console.error(e);
        showToast("Import Failed", "Failed to parse and import task details.", "error");
        btn.disabled = false;
        btn.innerHTML = originalText;
        lucide.createIcons();
    }
}

// Request new task from Telegram bot
async function handleRequestBotTask() {
    const btn = document.getElementById('btn-request-bot-task');
    const btnPrompt = document.getElementById('btn-start-task-prompt');
    const originalHTML = btn.innerHTML;
    const originalPromptHTML = btnPrompt.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner" style="width:14px; height:14px; border-width:2px; display:inline-block; margin-right:5px; vertical-align:middle;"></div> Requesting...';
    btnPrompt.disabled = true;
    btnPrompt.innerHTML = '<div class="spinner" style="width:14px; height:14px; border-width:2px; display:inline-block; margin-right:5px; vertical-align:middle;"></div> Starting...';

    showAutoCycleTracker("Starting Task...", "Connecting to @GmailFProBot and requesting details...");

    try {
        const res = await fetch(`${API_URL}/api/tasks/request-new`, {
            method: 'POST',
            headers: getHeaders()
        });

        const data = await res.json();
        if (res.status === 200) {
            showToast("New Task Assigned", data.message || "A new task has been assigned.", "success");
            hideAutoCycleTracker();
            // Reload active task
            await loadActiveTask();
        } else {
            showToast("Request Failed", data.detail || "Could not fetch new task.", "error");
            hideAutoCycleTracker();
        }
    } catch (e) {
        console.error(e);
        showToast("Network Error", "Failed to request task from bot.", "error");
        hideAutoCycleTracker();
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHTML;
        btnPrompt.disabled = false;
        btnPrompt.innerHTML = originalPromptHTML;
        lucide.createIcons();
    }
}

// Submit account details
async function handleTaskSubmit(e) {
    e.preventDefault();
    const taskId = document.getElementById('submit-task-id').value;
    const gmail = document.getElementById('gmail-address').value;
    const password = document.getElementById('gmail-password').value;
    
    const submitBtn = document.getElementById('submit-creds-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting...";
    
    try {
        const res = await fetch(`${API_URL}/api/tasks/submit`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                task_id: parseInt(taskId),
                gmail_address: gmail,
                gmail_password: password
            })
        });
        
        if (res.status === 200) {
            document.getElementById('task-submit-form').reset();
            showPipelineTracker("Submitting to bot...", "Routing registration info to bot over Telegram...");
            showToast("Credentials Submitted", "Your Gmail credentials have been sent for verification.", "info");
            // Start Polling
            startStatusPolling(taskId);
            // Refresh user pending balance
            await fetchCurrentUser();
            updateBalanceUI();
        } else {
            const err = await res.json();
            showToast("Submission Error", err.detail, "error");
            submitBtn.disabled = false;
            submitBtn.textContent = "Submit Credentials";
        }
    } catch (e) {
        showToast("Network Error", "Failed to submit task. Make sure server is reachable.", "error");
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit Credentials";
    }
}

// Poll Task verification states with auto-cycle
function startStatusPolling(taskId) {
    if (pollingInterval) clearInterval(pollingInterval);
    
    pollingInterval = setInterval(async () => {
        try {
            const res = await fetch(`${API_URL}/api/tasks/history`, {
                headers: getHeaders()
            });
            const history = await res.json();
            const task = history.find(t => t.id === parseInt(taskId));
            
            if (task) {
                if (task.status === 'verified') {
                    clearInterval(pollingInterval);
                    showPipelineTracker("Task Approved!", "Successfully verified by bot! Payout added to wallet.", "success");
                    showToast("Task Approved ✓", "Gmail account verified successfully! Payout credited.", "success", 6000);
                    await fetchCurrentUser();
                    updateBalanceUI();
                    loadWorkerHistory();
                    
                    // Auto-cycle: show fetching indicator, then reload task
                    setTimeout(() => {
                        showAutoCycleTracker("Fetching Next Task...", "Auto-requesting a new task from the Telegram bot...");
                        hidePipelineTracker();
                    }, 2500);
                    
                    setTimeout(async () => {
                        hideAutoCycleTracker();
                        await loadActiveTask();
                        document.getElementById('submit-creds-btn').disabled = false;
                        document.getElementById('submit-creds-btn').textContent = "Submit Credentials";
                        showToast("New Task Ready", "A new task has been auto-assigned. Start working!", "info");
                    }, 5000);
                    
                } else if (task.status === 'rejected') {
                    clearInterval(pollingInterval);
                    showPipelineTracker("Submission Rejected", `Validation failed: ${task.error_message || 'Verification rejected by bot.'}`, "danger");
                    showToast("Task Declined ✗", task.error_message || "Verification rejected by bot.", "error", 6000);
                    await fetchCurrentUser();
                    updateBalanceUI();
                    loadWorkerHistory();
                    
                    // Auto-cycle: show fetching indicator, then reload task
                    setTimeout(() => {
                        showAutoCycleTracker("Fetching Next Task...", "Auto-requesting a new task from the Telegram bot...");
                        hidePipelineTracker();
                    }, 3000);
                    
                    setTimeout(async () => {
                        hideAutoCycleTracker();
                        await loadActiveTask();
                        document.getElementById('submit-creds-btn').disabled = false;
                        document.getElementById('submit-creds-btn').textContent = "Submit Credentials";
                        showToast("New Task Ready", "A new task has been auto-assigned. Start working!", "info");
                    }, 6000);
                }
            }
        } catch (e) {
            console.error("Polling error", e);
        }
    }, 2500);
}

// Track progress elements helper
function showPipelineTracker(title, desc, status = 'pending') {
    document.getElementById('task-submit-form').classList.add('hidden');
    const tracker = document.getElementById('pipeline-tracker');
    tracker.classList.remove('hidden');
    
    const statusText = document.getElementById('pipeline-status');
    const statusDesc = document.getElementById('pipeline-description');
    
    statusText.textContent = title;
    statusDesc.textContent = desc;
    
    tracker.style.borderLeftColor = status === 'success' ? 'var(--success-green)' : (status === 'danger' ? 'var(--danger-red)' : 'var(--accent-cyan)');
    
    const loader = tracker.querySelector('.pipeline-loader');
    if (status === 'pending') {
        loader.classList.remove('hidden');
    } else {
        loader.classList.add('hidden');
    }
}

function hidePipelineTracker() {
    document.getElementById('task-submit-form').classList.remove('hidden');
    document.getElementById('pipeline-tracker').classList.add('hidden');
}

// Auto-cycle tracker helpers
function showAutoCycleTracker(title, desc) {
    const tracker = document.getElementById('auto-cycle-tracker');
    if (!tracker) return;
    tracker.classList.remove('hidden');
    document.getElementById('auto-cycle-status').textContent = title;
    document.getElementById('auto-cycle-description').textContent = desc;
}

function hideAutoCycleTracker() {
    const tracker = document.getElementById('auto-cycle-tracker');
    if (tracker) tracker.classList.add('hidden');
}

// Load task credentials submissions in table
async function loadWorkerHistory() {
    try {
        const res = await fetch(`${API_URL}/api/tasks/history`, {
            headers: getHeaders()
        });
        const history = await res.json();
        const tbody = document.getElementById('worker-history-body');
        tbody.innerHTML = '';
        
        if (history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center">No tasks submitted yet.</td></tr>';
            return;
        }
        
        history.forEach(task => {
            const tr = document.createElement('tr');
            
            // Format status badge
            let badgeClass = 'badge-pending';
            let statusText = task.status.toUpperCase();
            if (task.status === 'verified') {
                badgeClass = 'badge-success';
                statusText = 'APPROVED';
            }
            if (task.status === 'rejected') {
                badgeClass = 'badge-danger';
                statusText = 'DECLINED';
            }
            
            const dateStr = task.submitted_at ? new Date(task.submitted_at).toLocaleDateString() : 'N/A';
            
            tr.innerHTML = `
                <td>#${task.id}</td>
                <td>${task.gmail_address || '<span class="text-secondary">Unsubmitted</span>'}</td>
                <td><code>${task.gmail_password || 'N/A'}</code></td>
                <td>${task.recovery_email}</td>
                <td>${dateStr}</td>
                <td><span class="badge ${badgeClass}">${statusText}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
    }
}

// Request withdrawal
async function handleWithdrawSubmit(e) {
    e.preventDefault();
    const amount = parseFloat(document.getElementById('withdraw-amount').value);
    const method = document.getElementById('withdraw-method').value;
    const details = document.getElementById('withdraw-details').value;
    const errorDiv = document.getElementById('withdraw-error');
    
    errorDiv.classList.add('hidden');
    
    try {
        const res = await fetch(`${API_URL}/api/withdrawals/request`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ amount, payment_method: method, payment_details: details })
        });
        
        if (res.status === 200) {
            document.getElementById('withdraw-form').reset();
            closeModal('withdraw-modal');
            showToast("Withdrawal Submitted", "Your payout request has been submitted for admin review.", "success");
            await fetchCurrentUser();
            updateBalanceUI();
        } else {
            const err = await res.json();
            errorDiv.textContent = err.detail || "Validation failed";
            errorDiv.classList.remove('hidden');
        }
    } catch (e) {
        errorDiv.textContent = "Service unavailable. Try again later.";
        errorDiv.classList.remove('hidden');
    }
}

// ================= ADMIN CONSOLE FLOWS =================
async function loadAdminData() {
    try {
        // Load System Settings
        const configRes = await fetch(`${API_URL}/api/admin/config`, { headers: getHeaders() });
        const config = await configRes.json();
        
        document.getElementById('config-payout').value = config.payout_rate;
        document.getElementById('config-bot').value = config.telegram_bot_username;
        document.getElementById('config-sim').checked = config.simulation_mode === 1;
        document.getElementById('config-bot-routing').value = config.bot_routing_mode || 'system';
        
        // Load Workers Grid
        const workersRes = await fetch(`${API_URL}/api/admin/workers`, { headers: getHeaders() });
        const workers = await workersRes.json();
        const workersBody = document.getElementById('admin-workers-body');
        workersBody.innerHTML = '';
        
        if (workers.length === 0) {
            workersBody.innerHTML = '<tr><td colspan="6" class="text-center">No workers registered.</td></tr>';
        } else {
            workers.forEach(w => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>#${w.id}</td>
                    <td><strong>${w.username}</strong></td>
                    <td class="text-success">$${w.approved_balance.toFixed(2)}</td>
                    <td class="text-warning">$${w.pending_balance.toFixed(2)}</td>
                    <td>$${w.total_paid.toFixed(2)}</td>
                    <td>${new Date(w.created_at).toLocaleDateString()}</td>
                `;
                workersBody.appendChild(tr);
            });
        }
        
        // Load Payout Requests
        const withdrawsRes = await fetch(`${API_URL}/api/admin/withdrawals`, { headers: getHeaders() });
        const withdrawals = await withdrawsRes.json();
        const withdrawalsBody = document.getElementById('admin-withdrawals-body');
        withdrawalsBody.innerHTML = '';
        
        if (withdrawals.length === 0) {
            withdrawalsBody.innerHTML = '<tr><td colspan="8" class="text-center">No withdrawals processed.</td></tr>';
        } else {
            withdrawals.forEach(w => {
                const tr = document.createElement('tr');
                
                let badgeClass = 'badge-pending';
                if (w.status === 'approved') badgeClass = 'badge-success';
                if (w.status === 'rejected') badgeClass = 'badge-danger';
                
                let statusText = w.status.toUpperCase();
                if (w.status === 'rejected') statusText = 'DECLINED';
                
                let actionHTML = '<span class="text-secondary">-</span>';
                if (w.status === 'pending') {
                    actionHTML = `
                        <div class="user-controls">
                            <button onclick="approveWithdrawal(${w.id})" class="btn btn-primary" style="padding:0.4rem 0.8rem; font-size:0.8rem;"><i data-lucide="check"></i> Approve</button>
                            <button onclick="rejectWithdrawal(${w.id})" class="btn btn-danger" style="padding:0.4rem 0.8rem; font-size:0.8rem;"><i data-lucide="x"></i> Reject</button>
                        </div>
                    `;
                }
                
                tr.innerHTML = `
                    <td>#${w.id}</td>
                    <td>${w.worker_name}</td>
                    <td><strong>$${w.amount.toFixed(2)}</strong></td>
                    <td>${w.payment_method}</td>
                    <td><code>${w.payment_details}</code></td>
                    <td>${new Date(w.created_at).toLocaleDateString()}</td>
                    <td><span class="badge ${badgeClass}">${statusText}</span></td>
                    <td class="text-center">${actionHTML}</td>
                `;
                withdrawalsBody.appendChild(tr);
            });
            lucide.createIcons();
        }
        
        // Load bots pool
        loadBotsPool();
        
        // Load tasks admin
        loadGmailTasksAdmin();
        
        // Check Telegram Linkage state
        updateTelegramStatus();
    } catch (e) {
        console.error(e);
    }
}

// Update Telegram state cards
async function updateTelegramStatus() {
    try {
        const res = await fetch(`${API_URL}/api/admin/telegram/status`, { headers: getHeaders() });
        const data = await res.json();
        
        const dot = document.getElementById('tg-dot');
        const statusText = document.getElementById('tg-status-text');
        const infoText = document.getElementById('tg-info-text');
        const actionBtn = document.getElementById('tg-action-btn');
        
        if (data.is_connected) {
            dot.className = 'dot dot-green';
            statusText.textContent = "Connected";
            infoText.textContent = data.phone 
                ? `System connected and listening through account: ${data.phone}`
                : "System is connected in Simulation mode.";
            actionBtn.textContent = "Disconnect API";
            actionBtn.className = "btn btn-danger btn-block";
        } else {
            dot.className = 'dot dot-red';
            statusText.textContent = "Disconnected";
            infoText.textContent = "Configure API credentials and connect to authorize MTProto session.";
            actionBtn.textContent = "Connect Telegram";
            actionBtn.className = "btn btn-primary btn-block";
        }
    } catch (e) {
        console.error(e);
    }
}

// Handle Admin config save
async function handleConfigSubmit(e) {
    e.preventDefault();
    const rate = parseFloat(document.getElementById('config-payout').value);
    const bot = document.getElementById('config-bot').value;
    const sim = document.getElementById('config-sim').checked;
    const routing = document.getElementById('config-bot-routing').value;
    
    try {
        const res = await fetch(`${API_URL}/api/admin/config`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                payout_rate: rate,
                simulation_mode: sim ? 1 : 0,
                telegram_bot_username: bot,
                bot_routing_mode: routing
            })
        });
        
        if (res.status === 200) {
            showToast("Settings Saved", "System configuration updated successfully.", "success");
            loadAdminData();
        } else {
            showToast("Save Failed", "Failed to save system settings.", "error");
        }
    } catch (e) {
        showToast("Error", "Error saving settings.", "error");
    }
}

// Approve / Reject Payouts
async function approveWithdrawal(id) {
    if (!confirm("Are you sure you want to approve this withdrawal request?")) return;
    try {
        const res = await fetch(`${API_URL}/api/admin/withdrawals/${id}/approve`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (res.status === 200) {
            showToast("Payout Approved", "Withdrawal request has been approved and processed.", "success");
            loadAdminData();
        }
    } catch (e) {
        console.error(e);
    }
}

async function rejectWithdrawal(id) {
    if (!confirm("Are you sure you want to reject this withdrawal request? The worker will be refunded.")) return;
    try {
        const res = await fetch(`${API_URL}/api/admin/withdrawals/${id}/reject`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (res.status === 200) {
            showToast("Payout Rejected", "Withdrawal rejected and balance refunded to worker.", "warning");
            loadAdminData();
        }
    } catch (e) {
        console.error(e);
    }
}

window.approveWithdrawal = approveWithdrawal;
window.rejectWithdrawal = rejectWithdrawal;

// --- BOTS POOL MANAGEMENT ---
async function loadBotsPool() {
    try {
        const res = await fetch(`${API_URL}/api/admin/bots`, { headers: getHeaders() });
        const bots = await res.json();
        const tbody = document.getElementById('admin-bots-body');
        tbody.innerHTML = '';
        
        if (bots.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center">No bots added to pool.</td></tr>';
            return;
        }
        
        bots.forEach(b => {
            const tr = document.createElement('tr');
            
            const badgeClass = b.status === 'active' ? 'badge-success' : 'badge-pending';
            const actionText = b.status === 'active' ? 'Deactivate' : 'Activate';
            const btnClass = b.status === 'active' ? 'btn-secondary' : 'btn-primary';
            
            tr.innerHTML = `
                <td><strong>@${b.bot_username.replace('@', '')}</strong></td>
                <td><span class="badge ${badgeClass}">${b.status.toUpperCase()}</span></td>
                <td class="text-center">
                    <div style="display: flex; gap: 0.25rem; justify-content: center;">
                        <button onclick="toggleBotStatus(${b.id}, '${b.status}')" class="btn ${btnClass}" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;">${actionText}</button>
                        <button onclick="deleteBot(${b.id})" class="btn btn-danger" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;"><i data-lucide="trash-2"></i></button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
        lucide.createIcons();
    } catch (e) {
        console.error("Error loading bots pool:", e);
    }
}

async function handleBotSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('new-bot-username');
    const username = input.value.trim();
    if (!username) return;
    
    try {
        const res = await fetch(`${API_URL}/api/admin/bots`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ bot_username: username })
        });
        
        if (res.status === 200) {
            input.value = '';
            showToast("Bot Added", `@${username.replace('@', '')} added to the pool.`, "success");
            loadBotsPool();
        } else {
            const err = await res.json();
            showToast("Failed", err.detail || "Could not add bot.", "error");
        }
    } catch (e) {
        console.error(e);
        showToast("Error", "Error adding bot", "error");
    }
}

async function toggleBotStatus(id, currentStatus) {
    const nextStatus = currentStatus === 'active' ? 'inactive' : 'active';
    try {
        const res = await fetch(`${API_URL}/api/admin/bots/${id}/status`, {
            method: 'PATCH',
            headers: getHeaders(),
            body: JSON.stringify({ status: nextStatus })
        });
        if (res.status === 200) {
            loadBotsPool();
        }
    } catch (e) {
        console.error(e);
    }
}

async function deleteBot(id) {
    if (!confirm("Are you sure you want to delete this bot from the pool?")) return;
    try {
        const res = await fetch(`${API_URL}/api/admin/bots/${id}`, {
            method: 'DELETE',
            headers: getHeaders()
        });
        if (res.status === 200) {
            showToast("Bot Removed", "Bot deleted from pool.", "info");
            loadBotsPool();
        }
    } catch (e) {
        console.error(e);
    }
}

window.toggleBotStatus = toggleBotStatus;
window.deleteBot = deleteBot;

// --- GMAIL MANUAL VERIFICATION (Admin) ---
async function loadGmailTasksAdmin() {
    try {
        const res = await fetch(`${API_URL}/api/admin/tasks`, { headers: getHeaders() });
        const tasks = await res.json();
        const tbody = document.getElementById('admin-tasks-body');
        tbody.innerHTML = '';
        
        if (tasks.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center">No Gmail submissions available.</td></tr>';
            return;
        }
        
        tasks.forEach(task => {
            const tr = document.createElement('tr');
            
            let badgeClass = 'badge-pending';
            let statusText = task.status.toUpperCase();
            if (task.status === 'verified') {
                badgeClass = 'badge-success';
                statusText = 'APPROVED';
            }
            if (task.status === 'rejected') {
                badgeClass = 'badge-danger';
                statusText = 'DECLINED';
            }
            
            let actionHTML = '<span class="text-secondary">-</span>';
            if (task.status === 'submitted') {
                actionHTML = `
                    <div class="user-controls" style="justify-content: center; flex-wrap: wrap;">
                        <button onclick="approveGmailTask(${task.id})" class="btn btn-primary" style="padding:0.4rem 0.8rem; font-size:0.8rem;"><i data-lucide="check"></i> Approve</button>
                        <button onclick="rejectGmailTask(${task.id})" class="btn btn-danger" style="padding:0.4rem 0.8rem; font-size:0.8rem;"><i data-lucide="x"></i> Decline</button>
                        <button onclick="sendTaskToBot(${task.id})" class="btn-send-bot"><i data-lucide="send" style="width:12px;height:12px;"></i> Send to Bot</button>
                    </div>
                `;
            }
            
            const dateStr = task.submitted_at ? new Date(task.submitted_at).toLocaleDateString() : 'N/A';
            
            tr.innerHTML = `
                <td>#${task.id}</td>
                <td><strong>${task.worker_username || 'System'}</strong></td>
                <td>${task.gmail_address || '<span class="text-secondary">Unsubmitted</span>'}</td>
                <td><code>${task.gmail_password || 'N/A'}</code></td>
                <td>${task.recovery_email}</td>
                <td>${dateStr}</td>
                <td><span class="badge ${badgeClass}">${statusText}</span></td>
                <td class="text-center">${actionHTML}</td>
            `;
            tbody.appendChild(tr);
        });
        lucide.createIcons();
    } catch (e) {
        console.error("Error loading gmail tasks:", e);
    }
}

async function approveGmailTask(id) {
    if (!confirm("Are you sure you want to approve this Gmail account?")) return;
    try {
        const res = await fetch(`${API_URL}/api/admin/tasks/${id}/approve`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (res.status === 200) {
            showToast("Account Approved", "Gmail account approved. New task auto-assigned to worker.", "success");
            loadAdminData();
        } else {
            const err = await res.json();
            showToast("Error", err.detail, "error");
        }
    } catch (e) {
        console.error(e);
    }
}

async function rejectGmailTask(id) {
    const reason = prompt("Enter decline reason / error message:", "Manually declined by Admin");
    if (reason === null) return; // Cancelled
    try {
        const res = await fetch(`${API_URL}/api/admin/tasks/${id}/reject`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ error_message: reason })
        });
        if (res.status === 200) {
            showToast("Account Declined", "Gmail account rejected. New task auto-assigned to worker.", "warning");
            loadAdminData();
        } else {
            const err = await res.json();
            showToast("Error", err.detail, "error");
        }
    } catch (e) {
        console.error(e);
    }
}

async function sendTaskToBot(id) {
    if (!confirm("Send this task to the Telegram bot for automatic verification?")) return;
    try {
        const res = await fetch(`${API_URL}/api/admin/tasks/${id}/send-to-bot`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (res.status === 200) {
            showToast("Sent to Bot", "Task re-sent to Telegram bot for auto-verification.", "info");
            loadAdminData();
        } else {
            const err = await res.json();
            showToast("Error", err.detail || "Failed to send to bot.", "error");
        }
    } catch (e) {
        console.error(e);
    }
}

window.approveGmailTask = approveGmailTask;
window.rejectGmailTask = rejectGmailTask;
window.sendTaskToBot = sendTaskToBot;

// Handle Telegram setup buttons
async function handleTelegramAction() {
    const btn = document.getElementById('tg-action-btn');
    if (btn.classList.contains('btn-danger')) {
        // Disconnect
        if (!confirm("Disconnect the current Telegram link session?")) return;
        try {
            await fetch(`${API_URL}/api/admin/telegram/disconnect`, { method: 'POST', headers: getHeaders() });
            showToast("Disconnected", "Telegram session has been disconnected.", "info");
            updateTelegramStatus();
        } catch (e) {
            console.error(e);
        }
    } else {
        // Open link dialog
        document.getElementById('tg-connect-form').classList.remove('hidden');
        document.getElementById('tg-otp-form').classList.add('hidden');
        document.getElementById('tg-2fa-form').classList.add('hidden');
        openModal('telegram-link-modal');
    }
}

// Submit Phone + Credentials to Telegram
async function handleTGConnectSubmit(e) {
    e.preventDefault();
    const phone = document.getElementById('tg-phone').value;
    const apiId = document.getElementById('tg-api-id').value;
    const apiHash = document.getElementById('tg-api-hash').value;
    const errorDiv = document.getElementById('tg-connect-error');
    const connectBtn = document.getElementById('tg-connect-btn');
    
    errorDiv.classList.add('hidden');
    connectBtn.disabled = true;
    connectBtn.textContent = "Sending credentials...";
    
    try {
        const res = await fetch(`${API_URL}/api/admin/telegram/connect`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ phone, api_id: apiId, api_hash: apiHash })
        });
        
        const data = await res.json();
        if (res.status === 200 && data.status === 'otp_required') {
            phoneCodeHash = data.phone_code_hash;
            // Shift to OTP phase
            document.getElementById('tg-connect-form').classList.add('hidden');
            document.getElementById('tg-otp-form').classList.remove('hidden');
        } else {
            errorDiv.textContent = data.detail || "Connection request failed.";
            errorDiv.classList.remove('hidden');
        }
    } catch (err) {
        errorDiv.textContent = "Failed. Check endpoint configuration.";
        errorDiv.classList.remove('hidden');
    } finally {
        connectBtn.disabled = false;
        connectBtn.textContent = "Send OTP Code";
    }
}

// Submit OTP to Telegram
async function handleTGOTPSubmit(e) {
    e.preventDefault();
    const code = document.getElementById('tg-otp').value;
    const errorDiv = document.getElementById('tg-otp-error');
    const otpBtn = document.getElementById('tg-otp-btn');
    
    errorDiv.classList.add('hidden');
    otpBtn.disabled = true;
    otpBtn.textContent = "Verifying...";
    
    try {
        const res = await fetch(`${API_URL}/api/admin/telegram/verify-otp`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ code, phone_code_hash: phoneCodeHash })
        });
        
        const data = await res.json();
        if (res.status === 200) {
            if (data.status === 'success') {
                closeModal('telegram-link-modal');
                showToast("Telegram Linked", data.message, "success");
                loadAdminData();
            } else if (data.status === '2fa_required') {
                document.getElementById('tg-otp-form').classList.add('hidden');
                document.getElementById('tg-2fa-form').classList.remove('hidden');
            }
        } else {
            errorDiv.textContent = data.detail || "Validation code incorrect.";
            errorDiv.classList.remove('hidden');
        }
    } catch (err) {
        errorDiv.textContent = "Connection refused.";
        errorDiv.classList.remove('hidden');
    } finally {
        otpBtn.disabled = false;
        otpBtn.textContent = "Verify OTP Code";
    }
}

// Submit 2FA Password to Telegram
async function handleTG2FASubmit(e) {
    e.preventDefault();
    const password = document.getElementById('tg-2fa-password').value;
    const errorDiv = document.getElementById('tg-2fa-error');
    const btn = document.getElementById('tg-2fa-btn');
    
    errorDiv.classList.add('hidden');
    btn.disabled = true;
    btn.textContent = "Signing In...";
    
    try {
        const res = await fetch(`${API_URL}/api/admin/telegram/verify-otp`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ code: '', phone_code_hash: phoneCodeHash, password_2fa: password })
        });
        
        const data = await res.json();
        if (res.status === 200 && data.status === 'success') {
            closeModal('telegram-link-modal');
            showToast("Telegram Linked", data.message, "success");
            loadAdminData();
        } else {
            errorDiv.textContent = data.detail || "Invalid 2FA password.";
            errorDiv.classList.remove('hidden');
        }
    } catch (err) {
        errorDiv.textContent = "Verification request refused.";
        errorDiv.classList.remove('hidden');
    } finally {
        btn.disabled = false;
        btn.textContent = "Sign In";
    }
}

// ================= AUTHENTICATION HANDLERS =================
async function handleAuthSubmit(e) {
    e.preventDefault();
    const usernameInput = document.getElementById('username').value;
    const passwordInput = document.getElementById('password').value;
    const errorMsg = document.querySelector('.auth-error');
    const submitBtn = document.getElementById('auth-submit-btn');
    
    errorMsg.style.display = 'none';
    submitBtn.disabled = true;
    
    const path = isRegistering ? '/api/auth/register' : '/api/auth/login';
    submitBtn.querySelector('span').textContent = isRegistering ? 'Registering...' : 'Logging In...';
    
    try {
        const res = await fetch(`${API_URL}${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: usernameInput, password: passwordInput })
        });
        
        const data = await res.json();
        if (res.status === 200) {
            if (isRegistering) {
                // Swap back to login
                isRegistering = false;
                toggleAuthUI();
                showToast("Account Created", "Registration successful! Please log in.", "success");
            } else {
                // Save token
                apiToken = data.token;
                localStorage.setItem('gmail_farmer_token', apiToken);
                
                // Load profile and setup view
                await fetchCurrentUser();
                if (currentUser.role === 'admin') {
                    showTab('admin');
                } else {
                    showTab('worker');
                }
                initDashboard();
                showToast("Welcome Back", `Logged in as ${data.username}`, "info");
            }
        } else {
            errorMsg.textContent = data.detail || "Authentication failed. Try again.";
            errorMsg.style.display = 'block';
        }
    } catch (err) {
        errorMsg.textContent = "Network error. Make sure the server backend is running.";
        errorMsg.style.display = 'block';
    } finally {
        submitBtn.disabled = false;
        submitBtn.querySelector('span').textContent = isRegistering ? 'Register' : 'Log In';
    }
}

function toggleAuthUI() {
    const title = document.querySelector('.auth-header h2');
    const subtitle = document.getElementById('auth-subtitle');
    const submitText = document.querySelector('#auth-submit-btn span');
    const toggleText = document.getElementById('toggle-text');
    const toggleBtn = document.getElementById('toggle-auth-btn');
    
    document.querySelector('.auth-error').style.display = 'none';
    document.getElementById('auth-form').reset();
    
    if (isRegistering) {
        title.textContent = "Register Worker";
        subtitle.textContent = "Create an account to start claiming tasks";
        submitText.textContent = "Register";
        toggleText.textContent = "Already have an account?";
        toggleBtn.textContent = "Log in here";
    } else {
        title.textContent = "G-Farmer Task";
        subtitle.textContent = "Log in to start creating tasks and earning";
        submitText.textContent = "Log In";
        toggleText.textContent = "Don't have an account?";
        toggleBtn.textContent = "Register here";
    }
    lucide.createIcons();
}

function logout() {
    apiToken = '';
    currentUser = null;
    activeTask = null;
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
    localStorage.removeItem('gmail_farmer_token');
    showTab('auth');
}

// Setup Event Listeners
function setupEventListeners() {
    // Auth Toggler
    document.getElementById('toggle-auth-btn').addEventListener('click', (e) => {
        e.preventDefault();
        isRegistering = !isRegistering;
        toggleAuthUI();
    });
    
    // Auth Form
    document.getElementById('auth-form').addEventListener('submit', handleAuthSubmit);
    
    // Submit task credentials Form
    document.getElementById('task-submit-form').addEventListener('submit', handleTaskSubmit);
    
    // Parse task button
    document.getElementById('btn-parse-task').addEventListener('click', handleTaskImport);
    
    // Request new task from bot button
    document.getElementById('btn-request-bot-task').addEventListener('click', handleRequestBotTask);
    document.getElementById('btn-start-task-prompt').addEventListener('click', handleRequestBotTask);
    
    // Request withdrawal Form
    document.getElementById('withdraw-form').addEventListener('submit', handleWithdrawSubmit);
    
    // Admin Settings config Form
    document.getElementById('admin-config-form').addEventListener('submit', handleConfigSubmit);
    
    // Admin Add Bot Form
    document.getElementById('admin-add-bot-form').addEventListener('submit', handleBotSubmit);
    
    // Log out buttons
    document.querySelectorAll('.logout-btn').forEach(btn => {
        btn.addEventListener('click', logout);
    });
    
    // Tab toggler buttons
    document.getElementById('nav-admin-btn').addEventListener('click', () => {
        showTab('admin');
        initDashboard();
    });
    document.getElementById('nav-worker-btn').addEventListener('click', () => {
        showTab('worker');
        initDashboard();
    });
    
    // Withdrawal modal toggle
    document.getElementById('open-withdraw-btn').addEventListener('click', () => {
        openModal('withdraw-modal');
    });
    
    // Telegram connector steppers
    document.getElementById('tg-action-btn').addEventListener('click', handleTelegramAction);
    document.getElementById('tg-connect-form').addEventListener('submit', handleTGConnectSubmit);
    document.getElementById('tg-otp-form').addEventListener('submit', handleTGOTPSubmit);
    document.getElementById('tg-2fa-form').addEventListener('submit', handleTG2FASubmit);
}

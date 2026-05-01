/* ============================================
   PO Receiving App - Frontend JavaScript
   With Staff Authentication & Management
   ============================================ */

const app = {
    // Current state
    currentScreen: 'login',
    currentPO: null,
    selectedItems: [],
    selectedStorage: null,
    evidencePhoto: null,
    storageLocations: [],
    picklistItems: [],
    
    // OCR + Backorder state
    docketPhoto: null,
    docketOCRData: null,
    backorderItems: [],
    
    // Staff state
    currentStaff: null,
    staffList: [],
    editingStaffId: null,
    
    // Photo mode state
    photoMode: null,
    
    // Damage report state
    _damagePhotos: [],
    _damageItemIndex: null, // 'individual', 'group', or 'skip'
    individualPhotos: [], // [{itemIndex, description, base64}]
    
    // Relocate state
    relocateSourceId: null,
    relocateSourceName: null,
    relocateItems: [],
    relocateSelectedItems: [],
    relocateDestId: null,
    relocateDestName: null,
    relocateMode: 'location',
    relocateSearchResults: null,
    relocateMultiSource: false,
    suggestedStorageId: null,
    suggestedStorageName: null,
    
    // Stock selection state
    stockSelectedItems: [],
    stockSearchData: null,
    _stockReceivedItems: [],
    
    // ============================================
    // Initialization
    // ============================================
    init() {
        this.bindEvents();
        this.checkAuthStatus();
        
        // Prevent iOS overscroll bounce - simple CSS-only approach
        // All .screen elements use position:fixed via CSS
        // No JS intervention needed - JS fighting with iOS causes more bounce
    },
    
    bindEvents() {
        // Login
        document.getElementById('login-btn')?.addEventListener('click', () => this.login());
        document.getElementById('login-password')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.login();
        });
        document.getElementById('login-username')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') document.getElementById('login-password').focus();
        });
        
        // Logout
        document.getElementById('logout-btn')?.addEventListener('click', () => this.logout());
        
        // Home options
        document.getElementById('option-po')?.addEventListener('click', () => this.showScreen('scan'));
        document.getElementById('option-stock')?.addEventListener('click', () => this.showScreen('stock'));
        document.getElementById('job-lookup-btn')?.addEventListener('click', () => this.stockJobLookup());
        document.getElementById('job-number')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') this.stockJobLookup(); });
        document.getElementById('part-search-btn')?.addEventListener('click', () => this.stockPartSearch());
        document.getElementById('part-search')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') this.stockPartSearch(); });
        document.getElementById('stock-allocate-btn')?.addEventListener('click', () => this.allocateFromStock());
        document.getElementById('option-picklist')?.addEventListener('click', () => this.showPicklist());
        document.getElementById('option-relocate')?.addEventListener('click', () => this.showScreen('relocate-source'));
        document.getElementById('option-mystery')?.addEventListener('click', () => this.showScreen('mystery'));
        document.getElementById('mystery-search')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.searchMysteryBox();
        });
        document.getElementById('option-labels')?.addEventListener('click', () => this.showScreen('labels'));
        document.getElementById('option-sop')?.addEventListener('click', () => this.showScreen('sop'));
        document.getElementById('label-po-input')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.lookupLabels();
        });
        document.getElementById('label-lookup-btn')?.addEventListener('click', () => this.lookupLabels());
        
        // Relocate flow
        document.getElementById('relocate-source-dropdown')?.addEventListener('change', (e) => this.selectRelocateSource(e));
        document.getElementById('load-source-items-btn')?.addEventListener('click', () => this.loadRelocateItems());
        document.getElementById('relocate-select-all')?.addEventListener('change', (e) => this.toggleRelocateSelectAll(e));
        document.getElementById('to-relocate-dest-btn')?.addEventListener('click', () => this.showRelocateDestScreen());
        document.getElementById('relocate-dest-dropdown')?.addEventListener('change', (e) => this.selectRelocateDest(e));
        document.getElementById('execute-relocate-btn')?.addEventListener('click', () => this.executeRelocate());
        document.getElementById('relocate-another-btn')?.addEventListener('click', () => this.startNewRelocate());
        document.getElementById('relocate-home-btn')?.addEventListener('click', () => this.showHomeScreen());
        
        // Manager options
        document.getElementById('option-staff')?.addEventListener('click', () => this.showStaffManagement());
        document.getElementById('option-logs')?.addEventListener('click', () => this.showLogs());
        document.getElementById('add-staff-btn')?.addEventListener('click', () => this.showAddStaff());
        document.getElementById('staff-form')?.addEventListener('submit', (e) => this.saveStaff(e));
        
        // PO lookup
        document.getElementById('lookup-btn')?.addEventListener('click', () => this.lookupPO());
        document.getElementById('po-number')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.lookupPO();
        });
        
        // Camera captures
        document.getElementById('camera-capture')?.addEventListener('click', () => {
            document.getElementById('docket-photo')?.click();
        });
        document.getElementById('docket-photo')?.addEventListener('change', (e) => this.handleDocketPhoto(e));
        
        document.getElementById('evidence-capture')?.addEventListener('click', () => {
            document.getElementById('evidence-photo')?.click();
        });
        document.getElementById('evidence-photo')?.addEventListener('change', (e) => this.handleEvidencePhoto(e));
        document.getElementById('remove-evidence')?.addEventListener('click', () => this.removeEvidencePhoto());
        
        // Item selection
        document.getElementById('select-all')?.addEventListener('change', (e) => this.toggleSelectAll(e));
        document.getElementById('to-storage-btn')?.addEventListener('click', () => this.showJobMaterials());
        document.getElementById('continue-allocate-btn')?.addEventListener('click', () => this.continueToAllocate());
        
        // Storage selection
        document.getElementById('storage-dropdown')?.addEventListener('change', (e) => this.selectStorage(e));
        document.getElementById('allocate-btn')?.addEventListener('click', () => this.allocateItems());
        
        // Success screen
        document.getElementById('new-po-btn')?.addEventListener('click', () => this.startNewPO());
document.getElementById('view-history-btn')?.addEventListener('click', () => this.showLogs());
        document.getElementById('print-labels-btn')?.addEventListener('click', () => this.printLabels());
        
        // Back buttons
        document.querySelectorAll('.back-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const target = e.target.dataset.screen;
                if (target) this.showScreen(target);
            });
        });
    },
    
    // ============================================
    // Authentication
    // ============================================
    async checkAuthStatus() {
        // Try server auth check with retries
        for (let attempt = 0; attempt < 3; attempt++) {
            try {
                const response = await fetch('/api/auth/status');
                const data = await response.json();

                if (data.authenticated) {
                    this.currentStaff = data.staff;
                    localStorage.setItem('po_auth_cache', JSON.stringify({
                        staff: data.staff,
                        timestamp: Date.now()
                    }));
                    this.showHomeScreen();
                    return;
                } else {
                    localStorage.removeItem('po_auth_cache');
                    this.showScreen('login');
                    return;
                }
            } catch (error) {
                console.error('Auth check attempt ' + (attempt + 1) + ' failed:', error);
                if (attempt < 2) {
                    await new Promise(r => setTimeout(r, (attempt + 1) * 1500));
                }
            }
        }

        // All retries failed - server is down. Check localStorage cache
        const cached = localStorage.getItem('po_auth_cache');
        if (cached) {
            try {
                const { staff, timestamp } = JSON.parse(cached);
                if (Date.now() - timestamp < 24 * 60 * 60 * 1000) {
                    console.log('Using cached auth - server unreachable');
                    this.currentStaff = staff;
                    this.showHomeScreen();
                    return;
                }
            } catch(e) {}
        }

        this.showScreen('login');
    },
    
    async login() {
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');
        
        if (!username || !password) {
            errorEl.textContent = 'Please enter username and password';
            errorEl.style.display = 'block';
            return;
        }
        
        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.currentStaff = data.staff;
                errorEl.style.display = 'none';
                document.getElementById('login-password').value = '';
                // Cache auth for resilience
                localStorage.setItem('po_auth_cache', JSON.stringify({
                    staff: data.staff,
                    timestamp: Date.now()
                }));
                this.showHomeScreen();
            } else {
                errorEl.textContent = data.error || 'Invalid username or password';
                errorEl.style.display = 'block';
            }
        } catch (error) {
            console.error('Login error:', error);
            errorEl.textContent = 'Login failed. Please try again.';
            errorEl.style.display = 'block';
        }
    },
    
    async logout() {
        try {
            await fetch('/api/auth/logout', { method: 'POST' });
        } catch (error) {
            console.error('Logout error:', error);
        }
        
        this.currentStaff = null;
        localStorage.removeItem('po_auth_cache');
        document.getElementById('login-username').value = '';
        document.getElementById('login-password').value = '';
        document.getElementById('report-issue-fab')?.classList.add('hidden');
        this.showScreen('login');
    },
    
    showHomeScreen() {
        // Update staff name
        document.getElementById('staff-name').textContent = this.currentStaff?.displayName || 'Staff';
        
        // Show/hide manager options
        const managerOptions = document.getElementById('manager-options');
        if (this.currentStaff?.role === 'admin' || this.currentStaff?.role === 'manager') {
            managerOptions?.classList.remove('hidden');
        } else {
            managerOptions?.classList.add('hidden');
        }
        
        this.showScreen('home');
        this.loadPicklistCount();
        this.loadReceiptingStatus();
        
        // Show report issue button
        document.getElementById('report-issue-fab')?.classList.remove('hidden');
    },
    
    // ============================================
    // Staff Management
    // ============================================
    async showStaffManagement() {
        this.showScreen('staff-mgmt');
        await this.loadStaffList();
    },
    
    async loadStaffList() {
        const listEl = document.getElementById('staff-list');
        listEl.innerHTML = '<div class="loading">Loading staff...</div>';
        
        try {
            const response = await this.authFetch('/api/staff');
            const data = await response.json();
            
            if (data.staff) {
                this.staffList = data.staff;
                this.renderStaffList();
            } else {
                listEl.innerHTML = '<p>Failed to load staff list</p>';
            }
        } catch (error) {
            console.error('Load staff error:', error);
            listEl.innerHTML = '<p>Error loading staff list</p>';
        }
    },
    
    renderStaffList() {
        const listEl = document.getElementById('staff-list');
        
        if (this.staffList.length === 0) {
            listEl.innerHTML = '<p>No staff members found</p>';
            return;
        }
        
        const isAdmin = this.currentStaff?.role === 'admin';
        
        listEl.innerHTML = this.staffList.map(staff => {
            const initials = staff.display_name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
            const isCurrentUser = staff.id === this.currentStaff?.id;
            const canEdit = isAdmin || (staff.role === 'staff');
            
            return `
                <div class="staff-card ${staff.active ? '' : 'inactive'}">
                    <div class="staff-avatar">${initials}</div>
                    <div class="staff-info">
                        <div class="staff-name">${staff.display_name}${isCurrentUser ? ' (You)' : ''}</div>
                        <div class="staff-meta">
                            <span class="staff-role ${staff.role}">${staff.role}</span>
                            <span>@${staff.username}</span>
                            ${!staff.active ? '<span class="staff-status inactive">Disabled</span>' : ''}
                        </div>
                    </div>
                    ${canEdit && !isCurrentUser ? `
                        <div class="staff-actions-btns">
                            <button class="staff-edit-btn" onclick="app.editStaff(${staff.id})">✏️</button>
                            <button class="staff-toggle-btn ${staff.active ? '' : 'activate'}" 
                                    onclick="app.toggleStaffActive(${staff.id}, ${staff.active ? 'false' : 'true'})">
                                ${staff.active ? '🚫' : '✓'}
                            </button>
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
    },
    
    showAddStaff() {
        this.editingStaffId = null;
        document.getElementById('staff-modal-title').textContent = 'Add Staff Member';
        document.getElementById('staff-edit-id').value = '';
        document.getElementById('staff-username').value = '';
        document.getElementById('staff-username').disabled = false;
        document.getElementById('staff-display-name').value = '';
        document.getElementById('staff-password').value = '';
        document.getElementById('staff-password').required = true;
        document.getElementById('password-hint').textContent = '(min 6 characters)';
        document.getElementById('staff-role').value = 'staff';
        document.getElementById('staff-active').checked = true;
        
        // Only admins can create admins
        document.getElementById('admin-option').disabled = this.currentStaff?.role !== 'admin';
        
        document.getElementById('staff-modal').classList.remove('hidden');
    },
    
    editStaff(staffId) {
        const staff = this.staffList.find(s => s.id === staffId);
        if (!staff) return;
        
        this.editingStaffId = staffId;
        document.getElementById('staff-modal-title').textContent = 'Edit Staff Member';
        document.getElementById('staff-edit-id').value = staffId;
        document.getElementById('staff-username').value = staff.username;
        document.getElementById('staff-username').disabled = true; // Can't change username
        document.getElementById('staff-display-name').value = staff.display_name;
        document.getElementById('staff-password').value = '';
        document.getElementById('staff-password').required = false;
        document.getElementById('password-hint').textContent = '(leave blank to keep current)';
        document.getElementById('staff-role').value = staff.role;
        document.getElementById('staff-active').checked = staff.active;
        
        // Only admins can set admin role
        document.getElementById('admin-option').disabled = this.currentStaff?.role !== 'admin';
        
        document.getElementById('staff-modal').classList.remove('hidden');
    },
    
    closeStaffModal() {
        document.getElementById('staff-modal').classList.add('hidden');
        this.editingStaffId = null;
    },
    
    async saveStaff(event) {
        event.preventDefault();
        
        const staffId = this.editingStaffId;
        const username = document.getElementById('staff-username').value.trim();
        const displayName = document.getElementById('staff-display-name').value.trim();
        const password = document.getElementById('staff-password').value;
        const role = document.getElementById('staff-role').value;
        const active = document.getElementById('staff-active').checked;
        
        // Validation
        if (!displayName) {
            alert('Display name is required');
            return;
        }
        
        if (!staffId && !username) {
            alert('Username is required');
            return;
        }
        
        if (!staffId && (!password || password.length < 6)) {
            alert('Password must be at least 6 characters');
            return;
        }
        
        try {
            let response;
            
            if (staffId) {
                // Update existing staff
                const updateData = { displayName, role, active };
                if (password) updateData.password = password;
                
                response = await fetch(`/api/staff/${staffId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updateData)
                });
            } else {
                // Add new staff
                response = await this.authFetch('/api/staff', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, displayName, password, role })
                });
            }
            
            const data = await response.json();
            
            if (data.success || data.staff) {
                this.closeStaffModal();
                await this.loadStaffList();
            } else {
                alert(data.error || 'Failed to save staff member');
            }
        } catch (error) {
            console.error('Save staff error:', error);
            alert('Error saving staff member');
        }
    },
    
    async toggleStaffActive(staffId, activate) {
        const action = activate ? 'enable' : 'disable';
        if (!confirm(`Are you sure you want to ${action} this staff member?`)) {
            return;
        }
        
        try {
            const response = await fetch(`/api/staff/${staffId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ active: activate })
            });
            
            const data = await response.json();
            
            if (data.success) {
                await this.loadStaffList();
            } else {
                alert(data.error || 'Failed to update staff status');
            }
        } catch (error) {
            console.error('Toggle staff error:', error);
            alert('Error updating staff status');
        }
    },
    
    // ============================================
    // Allocation Logs
    // ============================================
    async showLogs() {
        this.showScreen('logs');
        await this.loadLogs();
    },
    
    async loadLogs() {
        const listEl = document.getElementById('logs-list');
        listEl.innerHTML = '<div class="loading">Loading logs...</div>';
        
        try {
            const response = await this.authFetch('/api/logs?limit=50');
            const data = await response.json();
            
            if (data.logs) {
                this.renderLogs(data.logs);
            } else {
                listEl.innerHTML = '<p>Failed to load logs</p>';
            }
        } catch (error) {
            console.error('Load logs error:', error);
            listEl.innerHTML = '<p>Error loading logs</p>';
        }
    },
    
    renderLogs(logs) {
        const listEl = document.getElementById('logs-list');
        
        if (logs.length === 0) {
            listEl.innerHTML = '<p style="text-align: center; color: #6b7280; padding: 40px;">No allocation logs yet</p>';
            return;
        }
        
        listEl.innerHTML = logs.map(log => {
            const date = new Date(log.created_at);
            const timeStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            
            return `
                <div class="log-card">
                    <div class="log-header">
                        <span class="log-po">PO #${log.po_number || 'N/A'}</span>
                        <span class="log-time">${timeStr}</span>
                    </div>
                    <div class="log-details">
                        <span class="log-label">Job:</span>
                        <span>${log.job_number || 'N/A'}</span>
                        <span class="log-label">Vendor:</span>
                        <span>${log.vendor_name || 'N/A'}</span>
                        <span class="log-label">Items:</span>
                        <span>${log.items_allocated} item(s)</span>
                        <span class="log-label">Location:</span>
                        <span>${log.storage_location || 'N/A'}</span>
                    </div>
                    <div class="log-staff">
                        ${log.staff_name}
                        ${log.verified ? '<span class="log-verified">✓ Verified</span>' : '<span class="log-verified failed">⚠ Not verified</span>'}
                    </div>
                </div>
            `;
        }).join('');
    },
    
    // ============================================
    // Screen Navigation
    // ============================================
    showScreen(screenId) {
        document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
        document.getElementById(`screen-${screenId}`)?.classList.add('active');
        this.currentScreen = screenId;
    },
    
    goHome() {
        this.showHomeScreen();
    },
    
    // ============================================
    // PO Operations
    // ============================================
    async lookupPO() {
        const poInput = document.getElementById('po-number');
        const poNumber = poInput.value.trim();
        
        if (!poNumber) {
            this.showStatus('scan-status', 'Please enter a PO number', 'error');
            return;
        }
        
        this.showStatus('scan-status', 'Looking up PO...', 'loading');
        
        try {
            const response = await fetch(`/api/po/${poNumber}`);
            const data = await response.json();
            
            if (data.error) {
                this.showStatus('scan-status', data.error, 'error');
                return;
            }
            
            this.currentPO = data;
            this.showVerifyScreen();
            
        } catch (error) {
            console.error('PO lookup error:', error);
            this.showStatus('scan-status', 'Failed to lookup PO', 'error');
        }
    },
    
    showVerifyScreen() {
        // Update PO info
        document.getElementById('po-title').textContent = `PO #${this.currentPO.poNumber}`;
        document.getElementById('po-vendor').textContent = this.currentPO.vendorName || 'Unknown Vendor';
        document.getElementById('po-job').textContent = this.currentPO.jobNumber 
            ? `Job ${this.currentPO.jobNumber}${this.currentPO.customerName ? ' - ' + this.currentPO.customerName : ''}`
            : 'No job linked';
        
        // Display due date
        const dueDateEl = document.getElementById('po-due-date');
        if (dueDateEl) {
            if (this.currentPO.dueDate) {
                const dueDate = new Date(this.currentPO.dueDate);
                const today = new Date();
                today.setHours(0,0,0,0);
                const isOverdue = dueDate < today;
                const formatted = dueDate.toLocaleDateString('en-AU', {day: 'numeric', month: 'short', year: 'numeric'});
                dueDateEl.innerHTML = `📅 Due: <strong>${formatted}</strong>${isOverdue ? ' <span class="overdue">⚠️ OVERDUE</span>' : ''}`;
                dueDateEl.className = 'po-due-date' + (isOverdue ? ' overdue' : '');
            } else {
                dueDateEl.innerHTML = '📅 Due: <em>Not set</em>';
                dueDateEl.className = 'po-due-date no-date';
            }
        }
        
        // Render items with editable quantities and backorder buttons
        const itemsList = document.getElementById('items-list');
        this.selectedItems = [];
        this.backorderItems = [];
        
        // Build items with CC grouping headers
        let lastCCId = null;
        let hasMultipleCCs = false;
        const uniqueCCs = new Set(this.currentPO.items.map(i => i.costCentreId).filter(Boolean));
        if (uniqueCCs.size > 1) hasMultipleCCs = true;
        
        itemsList.innerHTML = this.currentPO.items.map((item, index) => {
            const statusClass = item.receiptStatus === 'fully_receipted' ? 'receipted' 
                : item.receiptStatus === 'partially_receipted' ? 'partial' : 'pending';
            const statusText = item.receiptStatus === 'fully_receipted' ? 'Fully receipted'
                : item.receiptStatus === 'partially_receipted' ? 'Partially receipted' : 'Not yet receipted';
            const remaining = item.quantityOrdered - item.quantityReceived;
            
            // Add CC header if CC changed and there are multiple CCs
            let ccHeader = '';
            if (hasMultipleCCs && item.costCentreId && item.costCentreId !== lastCCId) {
                lastCCId = item.costCentreId;
                ccHeader = `<div class="cc-group-header">📋 ${item.costCentreName || 'Unknown Cost Centre'}</div>`;
            }
            
            return ccHeader + `
                <div class="item-card ${statusClass}" data-index="${index}" data-catalog-id="${item.catalogId}">
                    <label class="item-checkbox">
                        <input type="checkbox" onchange="app.toggleItem(${index})">
                        <span class="checkmark"></span>
                    </label>
                    <div class="item-details">
                        <div class="item-name">${item.description}</div>
                        <div class="item-meta">
                            ${item.partNo ? `<span class="item-part">${item.partNo}</span>` : ''}
                            ${item.jobNumber ? `<span class="item-job">Job ${item.jobNumber}${item.customerName ? ' - ' + item.customerName : ''}</span>` : item.allocationType === 'stock' ? '<span class="item-stock">📦 Stock</span>' : ''}
                            ${item.costCentreName ? `<span class="item-cc">📋 ${item.costCentreName}</span>` : ''}
                            <span class="item-qty">Ordered: ${item.quantityOrdered}</span>
                            <span class="item-received">Received: ${item.quantityReceived}</span>
                            ${item.storageLocation ? `<span class="item-storage">📍 ${item.storageLocation}</span>` : ''}
                        </div>
                        <div class="item-status ${statusClass}">${statusText}</div>
                    </div>
                    <div class="item-qty-controls">
                        <label class="qty-label">Qty:</label>
                        <input type="number" class="qty-input" id="qty-${index}" 
                               min="0" max="${remaining > 0 ? remaining : item.quantityOrdered}" value="${remaining > 0 ? remaining : item.quantityOrdered}"
                               onchange="app.updateItemQty(${index})" disabled>
                        <button class="backorder-btn" onclick="app.toggleBackorder(${index})" title="Mark as backordered">
                            BO
                        </button>
                        <button class="damage-btn" onclick="app.showDamageModal(${index})" title="Report damaged">
                            ⚠️
                        </button>
                    </div>
                </div>
            `;
        }).join('');
        
        this.updateSelectionCount();
        
        // Show "Print Labels" button if any items have storage locations (already allocated)
        const hasAllocatedItems = this.currentPO.items.some(item => 
            item.storageLocation && item.storageLocation !== 'Stock Holding'
        );
        const reprintBtn = document.getElementById('reprint-labels-btn');
        if (reprintBtn) {
            reprintBtn.classList.toggle('hidden', !hasAllocatedItems);
        }
        
        this.showScreen('verify');
    },
    
    async reprintLabels() {
        const po = this.currentPO;
        const items = po.items
            .filter(item => item.storageLocation && item.storageLocation !== 'Stock Holding')
            .map(item => ({
                jobNumber: item.jobNumber || po.jobNumber || '',
                customerName: item.customerName || po.customerName || '',
                partNo: item.partNo || '',
                description: item.description,
                quantity: item.quantityReceived || item.quantityOrdered,
                storageLocation: item.storageLocation
            }));
        
        if (items.length === 0) {
            alert('No allocated items to print labels for.');
            return;
        }
        
        await this.generateAndShowLabels(items, po.poNumber);
    },
    
    async lookupLabels() {
        const poInput = document.getElementById('label-po-input');
        const poNumber = poInput.value.trim();
        if (!poNumber) {
            alert('Please enter a PO number');
            return;
        }
        
        const lookupBtn = document.getElementById('label-lookup-btn');
        lookupBtn.disabled = true;
        lookupBtn.textContent = 'Looking up...';
        
        try {
            const response = await fetch(`/api/po/${poNumber}`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.error || 'PO not found');
            }
            
            const data = await response.json();
            this.labelPO = data;
            
            // Show PO info
            const infoCard = document.getElementById('label-po-info');
            document.getElementById('label-po-title').textContent = `PO #${data.poNumber}`;
            document.getElementById('label-po-vendor').textContent = data.vendorName || '';
            document.getElementById('label-po-job').textContent = data.jobNumber 
                ? `Job ${data.jobNumber}${data.customerName ? ' - ' + data.customerName : ''}`
                : 'No job linked';
            infoCard.style.display = 'block';
            
            // Show items with storage locations
            const itemsList = document.getElementById('label-items-list');
            const allocatedItems = data.items.filter(item => 
                item.storageLocation && item.storageLocation !== 'Stock Holding'
            );
            
            if (allocatedItems.length === 0) {
                itemsList.innerHTML = `
                    <div class="empty-state">
                        <p>⚠️ No allocated items found on this PO.</p>
                        <p>Items must be allocated to a storage location before labels can be printed.</p>
                    </div>
                `;
                document.getElementById('print-labels-btn2').classList.add('hidden');
            } else {
                itemsList.innerHTML = allocatedItems.map(item => `
                    <div class="item-card">
                        <div class="item-details">
                            <div class="item-name">${item.description}</div>
                            <div class="item-meta">
                                ${item.partNo ? `<span class="item-part">${item.partNo}</span>` : ''}
                                ${item.jobNumber ? `<span class="item-job">Job ${item.jobNumber}${item.customerName ? ' - ' + item.customerName : ''}</span>` : ''}
                                <span class="item-qty">Qty: ${item.quantityReceived || item.quantityOrdered}</span>
                                <span class="item-storage">📍 ${item.storageLocation}</span>
                            </div>
                        </div>
                    </div>
                `).join('');
                document.getElementById('print-labels-btn2').classList.remove('hidden');
            }
            
        } catch (err) {
            alert(err.message);
            document.getElementById('label-po-info').style.display = 'none';
            document.getElementById('label-items-list').innerHTML = '';
            document.getElementById('print-labels-btn2').classList.add('hidden');
        } finally {
            lookupBtn.disabled = false;
            lookupBtn.textContent = 'Look Up';
        }
    },
    
    async printLabelsFromScreen() {
        if (!this.labelPO) return;
        const po = this.labelPO;
        const items = po.items
            .filter(item => item.storageLocation && item.storageLocation !== 'Stock Holding')
            .map(item => ({
                jobNumber: item.jobNumber || po.jobNumber || '',
                customerName: item.customerName || po.customerName || '',
                partNo: item.partNo || '',
                description: item.description,
                quantity: item.quantityReceived || item.quantityOrdered,
                storageLocation: item.storageLocation
            }));
        
        if (items.length === 0) {
            alert('No allocated items to print labels for.');
            return;
        }
        
        await this.generateAndShowLabels(items, po.poNumber);
    },
    
    toggleItem(index) {
        const item = this.currentPO.items[index];
        const idx = this.selectedItems.findIndex(i => i.index === index);
        const qtyInput = document.getElementById(`qty-${index}`);
        const remaining = item.quantityOrdered - item.quantityReceived;
        
        if (idx >= 0) {
            this.selectedItems.splice(idx, 1);
            if (qtyInput) { qtyInput.disabled = true; }
        } else {
            // For fully receipted items (remaining=0), use the ordered quantity
            let qty;
            if (item.receiptStatus === 'fully_receipted' || remaining <= 0) {
                qty = qtyInput ? parseInt(qtyInput.value) || item.quantityOrdered : item.quantityOrdered;
            } else {
                qty = qtyInput ? parseInt(qtyInput.value) || remaining : remaining;
            }
            this.selectedItems.push({
                index,
                catalogId: item.catalogId,
                description: item.description,
                partNo: item.partNo,
                quantity: qty,
                receiptStatus: item.receiptStatus,
                quantityOrdered: item.quantityOrdered,
                quantityReceived: item.quantityReceived,
                jobNumber: item.jobNumber,
                customerName: item.customerName,
                allocationType: item.allocationType || null,
                allocationAssignedToId: item.allocationAssignedToId || null,
                jobId: item.jobId || null,
                sectionId: item.sectionId || null,
                costCentreId: item.costCentreId || null
            });
            if (qtyInput) { qtyInput.disabled = false; }
        }
        
        this.updateSelectionCount();
    },
    
    updateItemQty(index) {
        const item = this.currentPO.items[index];
        const qtyInput = document.getElementById(`qty-${index}`);
        if (!qtyInput) return;
        
        const remaining = item.quantityOrdered - item.quantityReceived;
        const maxQty = remaining > 0 ? remaining : item.quantityOrdered;
        let qty = parseInt(qtyInput.value) || 0;
        if (qty < 0) qty = 0;
        if (qty > maxQty) qty = maxQty;
        qtyInput.value = qty;
        
        const sel = this.selectedItems.find(i => i.index === index);
        if (sel) {
            sel.quantity = qty;
        }
    },
    
    toggleBackorder(index) {
        const item = this.currentPO.items[index];
        const btn = document.querySelector(`.item-card[data-index="${index}"] .backorder-btn`);
        const card = document.querySelector(`.item-card[data-index="${index}"]`);
        const boIdx = this.backorderItems.findIndex(i => i.index === index);
        
        if (boIdx >= 0) {
            this.backorderItems.splice(boIdx, 1);
            btn?.classList.remove('active');
            card?.classList.remove('backordered');
        } else {
            const remaining = item.quantityOrdered - item.quantityReceived;
            this.backorderItems.push({
                index,
                catalogId: item.catalogId,
                description: item.description,
                partNo: item.partNo,
                quantity: remaining,
                jobNumber: item.jobNumber,
                customerName: item.customerName
            });
            btn?.classList.add('active');
            card?.classList.add('backordered');
        }
    },
    
    toggleSelectAll(event) {
        const checked = event.target.checked;
        const checkboxes = document.querySelectorAll('#items-list input[type="checkbox"]');
        
        this.selectedItems = [];
        
        checkboxes.forEach((cb, index) => {
            cb.checked = checked;
            const qtyInput = document.getElementById(`qty-${index}`);
            if (checked) {
                const item = this.currentPO.items[index];
                const remaining = item.quantityOrdered - item.quantityReceived;
                const effectiveQty = remaining > 0 ? remaining : item.quantityOrdered;
                const qty = qtyInput ? parseInt(qtyInput.value) || effectiveQty : effectiveQty;
                this.selectedItems.push({
                    index,
                    catalogId: item.catalogId,
                    description: item.description,
                    partNo: item.partNo,
                    quantity: qty,
                    receiptStatus: item.receiptStatus,
                    quantityOrdered: item.quantityOrdered,
                    quantityReceived: item.quantityReceived,
                    jobNumber: item.jobNumber,
                    customerName: item.customerName,
                    allocationType: item.allocationType || null,
                    allocationAssignedToId: item.allocationAssignedToId || null,
                    jobId: item.jobId || null,
                    sectionId: item.sectionId || null,
                    costCentreId: item.costCentreId || null
                });
                if (qtyInput) { qtyInput.disabled = false; }
            } else {
                if (qtyInput) { qtyInput.disabled = true; }
            }
        });
        
        this.updateSelectionCount();
    },
    
    updateSelectionCount() {
        const count = this.selectedItems.length;
        const total = this.currentPO?.items?.length || 0;
        
        document.getElementById('selection-count').textContent = `${count} of ${total} items selected`;
        document.getElementById('to-storage-btn').disabled = count === 0;
        
        // Update storage screen
        document.getElementById('storage-item-count').textContent = count;
    },
    
    // ============================================
    // Storage Selection

    // ============================================
    // Job Materials Overview (before storage selection)
    // ============================================
    async showJobMaterials() {
        // Collect unique job IDs from selected items
        const jobIds = new Set();
        for (const sel of this.selectedItems) {
            const item = this.currentPO.items[sel.index];
            if (item.jobNumber && /^\d+$/.test(String(item.jobNumber))) {
                jobIds.add(String(item.jobNumber));
            }
        }
        
        // If no valid jobs (stock order), skip straight to storage
        if (jobIds.size === 0) {
            this.suggestedStorageId = null;
            this.suggestedStorageName = null;
            document.getElementById('storage-item-count').textContent = this.selectedItems.length;
            this.showScreen('storage');
            return;
        }
        
        this.showScreen('job-materials');
        document.getElementById('job-materials-loading').classList.remove('hidden');
        document.getElementById('job-materials-content').classList.add('hidden');
        
        try {
            let html = '';
            let bestStorageId = null;
            let bestStorageName = null;
            let bestStorageCount = 0;
            
            for (const jobId of jobIds) {
                const resp = await this.authFetch('/api/job-intel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: parseInt(jobId) }),
                    cache: 'no-store'
                });
                
                if (!resp.ok) continue;
                const data = await resp.json();
                
                // Job header
                html += '<div class="job-materials-card">';
                html += '<div class="job-materials-header">';
                html += '<div class="job-materials-title">Job ' + jobId + '</div>';
                html += '<div class="job-materials-customer">' + (data.job.customer || '') + '</div>';
                if (data.job.site) html += '<div class="job-materials-site">\ud83d\udccd ' + data.job.site + '</div>';
                html += '</div>';
                
                // Progress bar
                const s = data.summary;
                if (s && s.totalRequired > 0) {
                    const pct = Math.round((s.totalAssigned / s.totalRequired) * 100);
                    html += '<div class="jm-progress">';
                    html += '<div class="jm-progress-bar"><div class="jm-progress-fill" style="width:' + pct + '%"></div></div>';
                    html += '<span class="jm-progress-text">' + s.totalAssigned + ' of ' + s.totalRequired + ' items allocated</span>';
                    html += '</div>';
                }
                
                // Already allocated - grouped by storage location
                if (data.storageLocations && data.storageLocations.length > 0) {
                    html += '<div class="jm-section-title">\ud83d\udce6 Already Allocated</div>';
                    for (const loc of data.storageLocations) {
                        if (loc.items && loc.items.length > bestStorageCount) {
                            bestStorageCount = loc.items.length;
                            bestStorageId = loc.id;
                            bestStorageName = loc.name;
                        }
                        
                        html += '<div class="jm-storage-loc">';
                        html += '<div class="jm-loc-name">\ud83d\udccd ' + loc.name + ' <span class="jm-loc-count">(' + loc.items.length + ' items)</span></div>';
                        html += '<div class="jm-loc-items">';
                        for (const item of loc.items.slice(0, 20)) {
                            html += '<div class="jm-item">\u2022 ' + (item.partNo ? '<span class="jm-part">' + item.partNo + '</span> ' : '') + item.name + ' <span class="jm-qty">\u00d7' + item.qty + '</span></div>';
                        }
                        if (loc.items.length > 20) {
                            html += '<div class="jm-item jm-more">+ ' + (loc.items.length - 20) + ' more items</div>';
                        }
                        html += '</div></div>';
                    }
                }
                
                // Pending items
                const pending = (data.stock || []).filter(function(st) { return st.pending > 0; });
                if (pending.length > 0) {
                    html += '<div class="jm-section-title">\u23f3 Still Awaiting (' + pending.length + ' items)</div>';
                    html += '<div class="jm-pending-items">';
                    for (const item of pending.slice(0, 25)) {
                        html += '<div class="jm-item">\u2022 ' + (item.partNo ? '<span class="jm-part">' + item.partNo + '</span> ' : '') + item.name + ' <span class="jm-qty">\u00d7' + item.pending + '</span></div>';
                    }
                    if (pending.length > 25) {
                        html += '<div class="jm-item jm-more">+ ' + (pending.length - 25) + ' more items</div>';
                    }
                    html += '</div>';
                }
                
                html += '</div>';
            }
            
            // Store suggested storage for auto-select
            this.suggestedStorageId = bestStorageId;
            this.suggestedStorageName = bestStorageName;
            
            // Suggestion banner at top
            if (bestStorageName) {
                html = '<div class="jm-suggestion">\ud83d\udca1 Items for this job are already in <strong>' + bestStorageName + '</strong></div>' + html;
            }
            
            if (!html) {
                html = '<div class="jm-no-materials"><p>No materials found for this job yet.</p><p>This will be the first allocation.</p></div>';
            }
            
            document.getElementById('job-materials-loading').classList.add('hidden');
            document.getElementById('job-materials-content').innerHTML = html;
            document.getElementById('job-materials-content').classList.remove('hidden');
            
        } catch (e) {
            console.error('Job materials error:', e);
            document.getElementById('job-materials-loading').classList.add('hidden');
            document.getElementById('job-materials-content').innerHTML = '<div style="color: #ef4444; padding: 20px; text-align: center;">Could not load job materials. You can still continue to allocate.</div>';
            document.getElementById('job-materials-content').classList.remove('hidden');
        }
    },
    
    continueToAllocate() {
        document.getElementById('storage-item-count').textContent = this.selectedItems.length;
        this.showScreen('storage');
        
        // Auto-select suggested storage if available
        if (this.suggestedStorageId) {
            const dropdown = document.getElementById('storage-dropdown');
            if (dropdown) {
                dropdown.value = String(this.suggestedStorageId);
                // Trigger change event to update state
                dropdown.dispatchEvent(new Event('change'));
            }
        }
    },

    // Wrapper for fetch that handles 401 gracefully
    async authFetch(url, options = {}) {
        try {
            const response = await fetch(url, options);
            if (response.status === 401) {
                // Session expired — redirect to login smoothly
                this.currentStaff = null;
                localStorage.removeItem('po_auth_cache');
                this.showScreen('login');
                throw new Error('Session expired. Please log in again.');
            }
            return response;
        } catch (error) {
            if (error.message === 'Session expired. Please log in again.') {
                throw error;
            }
            throw error;
        }
    },


    // ============================================
    selectStorage(event) {
        const select = event.target;
        const selectedOption = select.options[select.selectedIndex];
        
        if (select.value) {
            this.selectedStorage = {
                id: parseInt(select.value),
                name: selectedOption.textContent
            };
            this._lastStorageName = selectedOption.textContent;
            document.getElementById('allocate-btn').disabled = false;
        } else {
            this.selectedStorage = null;
            document.getElementById('allocate-btn').disabled = true;
        }
    },
    
    // ============================================
    // Allocation
    // ============================================
    async allocateItems() {
        if (!this.selectedStorage || this.selectedItems.length === 0) {
            alert('Please select items and a storage location');
            return;
        }
        
        this.showScreen('processing');
        document.getElementById('processing-status').textContent = 'Allocating items in Simpro...';
        
        try {
            const response = await this.authFetch('/api/allocate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                cache: 'no-store',
                body: JSON.stringify({
                    poId: this.currentPO.poId,
                    poNumber: this.currentPO.poNumber,
                    jobNumber: this.currentPO.jobNumber,
                    vendorName: this.currentPO.vendorName,
                    items: this.selectedItems.map(item => ({
                        catalogId: item.catalogId,
                        partNo: item.partNo || '',
                        description: item.description || '',
                        quantity: item.quantity || item.quantityOrdered || 1,
                        receiptStatus: item.receiptStatus || 'not_receipted',
                        quantityOrdered: item.quantityOrdered || 0,
                        quantityReceived: item.quantityReceived || 0,
                        allocationType: item.allocationType || null,
                        allocationAssignedToId: item.allocationAssignedToId || null
                    })),
                    storageDeviceId: this.selectedStorage.id,
                    storageName: this.selectedStorage.name
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Save backorder items if any
                if (this.backorderItems.length > 0) {
                    try {
                        await this.authFetch('/api/backorder', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                poId: this.currentPO.poId,
                                poNumber: this.currentPO.poNumber,
                                vendorName: this.currentPO.vendorName,
                                items: this.backorderItems
                            })
                        });
                    } catch (boErr) {
                        console.error('Backorder save error:', boErr);
                    }
                }
                
                // Save docket OCR data if available
                if (this.docketOCRData) {
                    try {
                        await this.authFetch('/api/docket-data', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                poId: this.currentPO.poId,
                                poNumber: this.currentPO.poNumber,
                                ...this.docketOCRData
                            })
                        });
                    } catch (dErr) {
                        console.error('Docket data save error:', dErr);
                    }
                }
                
                // Upload photos to Simpro
                let photoUploadResult = null;
                if (this.photoMode && this.photoMode !== 'skip') {
                    try {
                        document.getElementById('processing-status').textContent = 'Uploading photos to Simpro...';
                        
                        const photos = [];
                        const dateStr = new Date().toISOString().split('T')[0];
                        
                        if (this.photoMode === 'group' && this.evidencePhoto) {
                            photos.push({
                                base64: this.evidencePhoto,
                                filename: `PO_${this.currentPO.poNumber}_${(this.selectedStorage?.name || 'unknown').replace(/[^a-zA-Z0-9]/g, '_')}_delivery_${dateStr}.jpg`
                            });
                        } else if (this.photoMode === 'individual') {
                            this.individualPhotos.forEach(p => {
                                const safeName = (p.partNo || p.description || 'item').replace(/[^a-zA-Z0-9]/g, '_').substring(0, 30);
                                photos.push({
                                    base64: p.base64,
                                    filename: `PO_${this.currentPO.poNumber}_${(this.selectedStorage?.name || 'unknown').replace(/[^a-zA-Z0-9]/g, '_')}_${safeName}_${dateStr}.jpg`
                                });
                            });
                        }
                        
                        if (photos.length > 0) {
                            // Collect unique job IDs from selected items
                            const jobIds = [...new Set(
                                this.selectedItems
                                    .map(item => item.jobNumber)
                                    .filter(j => j && j !== 'N/A')
                            )];
                            
                            // Fallback to PO-level job
                            if (jobIds.length === 0 && this.currentPO.jobNumber && this.currentPO.jobNumber !== 'N/A') {
                                jobIds.push(this.currentPO.jobNumber);
                            }
                            
                            if (jobIds.length > 0) {
                                const uploadResp = await this.authFetch('/api/upload-photos', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        poNumber: this.currentPO.poNumber,
                                        poSimproId: this.currentPO.poId,
                                        jobIds: jobIds,
                                        photos: photos
                                    })
                                });
                                photoUploadResult = await uploadResp.json();
                            }
                        }
                    } catch (photoErr) {
                        console.error('Photo upload error:', photoErr);
                    }
                }
                
                // Pass photo result to success screen
                data.photoUploadResult = photoUploadResult;
                
                this.showSuccessScreen(data);
            } else {
                alert('Allocation failed: ' + (data.error || 'Unknown error'));
                this.showScreen('storage');
            }
            
        } catch (error) {
            console.error('Allocation error:', error);
            alert('Allocation failed: ' + error.message);
            this.showScreen('storage');
        }
    },
    
    showSuccessScreen(data) {
        document.getElementById('success-summary').innerHTML = `
            <strong>${data.successCount}</strong> item(s) → <strong>${this.selectedStorage.name}</strong>
        `;
        
        document.getElementById('success-staff-name').textContent = data.allocatedBy || this.currentStaff?.displayName || 'Staff';
        
        // Show verification status
        const verifyEl = document.getElementById('success-verification');
        if (verifyEl) {
            let statusHtml = '';
            if (data.allVerified) {
                statusHtml += '<div style="color: #22c55e;">✅ Verified in Simpro</div>';
            } else {
                statusHtml += '<div style="color: #f59e0b;">⚠️ Allocation sent - verification pending</div>';
            }
            // Show Goods Received status
            if (data.goodsReceivedSet) {
                statusHtml += '<div style="color: #22c55e; margin-top: 4px;">✅ Goods Received status set</div>';
            } else if (data.successCount > 0) {
                statusHtml += '<div style="color: #f59e0b; margin-top: 4px;">⚠️ Goods Received status pending</div>';
            }
            verifyEl.innerHTML = statusHtml;
        }
        
        // Show backorder info
        const boEl = document.getElementById('success-backorder');
        if (boEl) {
            if (this.backorderItems.length > 0) {
                boEl.style.display = 'block';
                boEl.innerHTML = `<span style="color: #f59e0b;">⚠️ ${this.backorderItems.length} item(s) marked as backordered</span>`;
            } else {
                boEl.style.display = 'none';
            }
        }
        
        // Photo upload status
        const photoEl = document.getElementById('success-photo');
        if (data.photoUploadResult) {
            if (data.photoUploadResult.success) {
                const jobCount = data.photoUploadResult.jobUploads || 0;
                const poCount = data.photoUploadResult.poUploads || 0;
                let uploadMsg = '📸 Photos uploaded to Simpro: ';
                const parts = [];
                if (jobCount > 0) parts.push(`${jobCount} to Job`);
                if (poCount > 0) parts.push(`${poCount} to PO`);
                uploadMsg += parts.join(', ') || `${data.photoUploadResult.uploaded} total`;
                photoEl.innerHTML = `<span style="color: #22c55e;">${uploadMsg}</span>`;
            } else {
                photoEl.innerHTML = `<span style="color: #f59e0b;">⚠️ Photo upload: ${data.photoUploadResult.error || 'partial failure'}</span>`;
            }
            photoEl.style.display = 'block';
        } else if (this.photoMode === 'skip' || !this.photoMode) {
            photoEl.style.display = 'none';
        } else {
            photoEl.style.display = 'none';
        }
        
        // Label count
        const totalLabels = this.selectedItems.reduce((sum, item) => sum + item.quantity, 0);
        const hasJobForLabels = this.currentPO?.jobNumber && this.currentPO.jobNumber !== 'N/A' && this.currentPO.jobNumber !== 'Stock';
        document.getElementById('label-count').textContent = hasJobForLabels 
            ? `${totalLabels} item labels + 1 filing label`
            : `${totalLabels} labels ready to print`;
        
        // Show picking slip button (always available after allocation)
        const pickSlipSection = document.getElementById('picking-slip-section');
        if (pickSlipSection) {
            pickSlipSection.style.display = 'block';
            document.getElementById('picking-slip-status').textContent = 'Generate a picking slip for field workers';
            const pickBtn = document.getElementById('generate-picking-slip-btn');
            if (pickBtn) {
                pickBtn.disabled = false;
                pickBtn.textContent = '📋 Generate Picking Slip';
            }
        }
        
        this.showScreen('success');
        
        // Load job intel in background
        this.loadJobIntel();
    },
    

    // ============================================
    // Job Intel - show stock status for allocated jobs
    // ============================================
    async loadJobIntel() {
        const container = document.getElementById('job-intel-section');
        const content = document.getElementById('job-intel-content');
        if (!container || !content) return;
        
        // Collect unique numeric job IDs from current PO items
        const jobIds = new Set();
        if (this.currentPO?.items) {
            for (const item of this.currentPO.items) {
                if (item.jobNumber && /^\d+$/.test(String(item.jobNumber))) {
                    jobIds.add(String(item.jobNumber));
                }
            }
        }
        
        if (jobIds.size === 0) {
            container.style.display = 'none';
            return;
        }
        
        container.style.display = 'block';
        content.innerHTML = '<div class="loading-small">Loading job intel...</div>';
        
        try {
            let html = '';
            for (const jobId of jobIds) {
                const resp = await this.authFetch('/api/job-intel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: parseInt(jobId) }),
                    cache: 'no-store'
                });
                
                if (!resp.ok) continue;
                const data = await resp.json();
                
                // Job header
                html += '<div class="job-intel-card">';
                html += '<div class="job-intel-header">';
                html += '<strong>Job ' + jobId + '</strong> &middot; ' + (data.job.customer || 'Unknown');
                if (data.job.site) html += '<br><small>\ud83d\udccd ' + data.job.site + '</small>';
                html += '</div>';
                
                // Summary progress
                const s = data.summary;
                if (s.isComplete) {
                    html += '<div class="job-intel-complete">\u2705 All ' + s.totalRequired + ' items received &mdash; job materials complete!</div>';
                } else if (s.totalRequired > 0) {
                    const pct = Math.round((s.totalAssigned / s.totalRequired) * 100);
                    html += '<div class="job-intel-progress">';
                    html += '<div class="progress-bar"><div class="progress-fill" style="width:' + pct + '%"></div></div>';
                    html += '<span>' + s.totalAssigned + ' of ' + s.totalRequired + ' received &middot; ' + s.totalPending + ' pending</span>';
                    html += '</div>';
                }
                
                // Storage locations with items already there
                if (data.storageLocations && data.storageLocations.length > 0) {
                    html += '<div class="job-intel-storage">';
                    html += '<div class="storage-title">\ud83d\udce6 Already in storage:</div>';
                    for (const loc of data.storageLocations) {
                        html += '<div class="storage-loc">';
                        html += '<strong>' + loc.name + '</strong>';
                        for (const item of loc.items.slice(0, 10)) {
                            const label = (item.partNo ? item.partNo + ' ' : '') + item.name;
                            html += '<div class="storage-item">&middot; ' + label + ' (&times;' + item.qty + ')</div>';
                        }
                        if (loc.items.length > 10) {
                            html += '<div class="storage-item" style="font-style:italic;">&middot; +' + (loc.items.length - 10) + ' more items</div>';
                        }
                        html += '</div>';
                    }
                    html += '</div>';
                }
                
                // Pending items
                const pending = (data.stock || []).filter(s => s.pending > 0);
                if (pending.length > 0) {
                    html += '<div class="job-intel-pending">';
                    html += '<div class="pending-title">\u23f3 Still awaiting:</div>';
                    for (const item of pending.slice(0, 15)) {
                        const label = (item.partNo ? item.partNo + ' ' : '') + item.name;
                        html += '<div class="pending-item">&middot; ' + label + ' (&times;' + item.pending + ')</div>';
                    }
                    if (pending.length > 15) {
                        html += '<div class="pending-item" style="font-style:italic;">&middot; +' + (pending.length - 15) + ' more items</div>';
                    }
                    html += '</div>';
                }
                
                html += '</div>';  // close job-intel-card
            }
            
            content.innerHTML = html || '<div>No job data available</div>';
        } catch (e) {
            console.error('Job intel error:', e);
            content.innerHTML = '<div style="color: #f59e0b;">\u26a0\ufe0f Could not load job intel</div>';
        }
    },
    
    startNewPO() {
        this.currentPO = null;
        this.selectedItems = [];
        this.selectedStorage = null;
        this.docketPhoto = null;
        this.docketOCRData = null;
        this.backorderItems = [];
        this.photoMode = null;
        this.individualPhotos = [];
        this.evidencePhoto = null;
        document.getElementById('po-number').value = '';
        document.getElementById('storage-dropdown').value = '';
        document.getElementById('allocate-btn').disabled = true;
        document.getElementById('select-all').checked = false;
        // Reset OCR UI
        const ocrProgress = document.getElementById('ocr-progress');
        const ocrResult = document.getElementById('ocr-result');
        if (ocrProgress) ocrProgress.classList.remove('active');
        if (ocrResult) ocrResult.style.display = 'none';
        this.showScreen('scan');
    },
    
    // ============================================
    // Picking Slip Generation
    // ============================================
    async generatePickingSlip() {
        const btn = document.getElementById('generate-picking-slip-btn');
        const statusEl = document.getElementById('picking-slip-status');
        
        if (!this.currentPO || !this.selectedItems.length) {
            statusEl.textContent = '⚠️ No items to generate slip for';
            return;
        }
        
        btn.disabled = true;
        btn.textContent = '⏳ Generating...';
        statusEl.textContent = 'Creating PDF and uploading to Simpro...';
        
        try {
            // Build items list with storage location
            const items = this.selectedItems.map(item => ({
                description: item.description,
                partNo: item.partNo || '',
                quantity: item.quantity,
                storageLocation: this.selectedStorage?.name || 'Unknown'
            }));
            
            const response = await this.authFetch('/api/picking-slip/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    poId: this.currentPO.poId,
                    poNumber: this.currentPO.poNumber,
                    jobNumber: this.currentPO.jobNumber || '',
                    vendorName: this.currentPO.vendorName || '',
                    customerName: this.currentPO.customerName || '',
                    items: items
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                btn.textContent = '✅ Picking Slip Uploaded';
                statusEl.innerHTML = `<span style="color: #22c55e;">✅ Picking slip uploaded to Job ${data.jobNumber || ''} in Simpro</span>`;
            } else {
                btn.textContent = '📋 Retry';
                btn.disabled = false;
                statusEl.innerHTML = `<span style="color: #dc2626;">❌ ${data.error || 'Failed to generate'}</span>`;
            }
        } catch (error) {
            console.error('Picking slip error:', error);
            btn.textContent = '📋 Retry';
            btn.disabled = false;
            statusEl.innerHTML = `<span style="color: #dc2626;">❌ Error: ${error.message}</span>`;
        }
    },
    
    // ============================================
    // Pick List
    // ============================================
    async loadPicklistCount() {
        try {
            const response = await this.authFetch('/api/stock-pick-list');
            const data = await response.json();
            const count = data.count || 0;
            
            const badge = document.getElementById('picklist-badge');
            badge.textContent = count;
            badge.style.display = count > 0 ? 'flex' : 'none';
        } catch (error) {
            console.error('Picklist count error:', error);
        }
    },
    
    async showPicklist() {
        this.showScreen('picklist');
        
        try {
            const response = await this.authFetch('/api/stock-pick-list');
            const data = await response.json();
            
            this.picklistItems = data.items || [];
            document.getElementById('stat-ready').textContent = this.picklistItems.length;
            
        } catch (error) {
            console.error('Picklist error:', error);
        }
    },
    
    // ============================================
    // Photos
    // ============================================
    async handleDocketPhoto(event) {
        const file = event.target.files[0];
        if (!file) return;
        
        // Compress and store docket photo as base64
        try {
            this.docketPhoto = await this.compressImage(file);
        } catch(e) {
            const reader = new FileReader();
            reader.onload = (ev) => { this.docketPhoto = ev.target.result; };
            reader.readAsDataURL(file);
        }
        
        // Show OCR progress
        const ocrProgress = document.getElementById('ocr-progress');
        const ocrResult = document.getElementById('ocr-result');
        const ocrStatusText = document.getElementById('ocr-status-text');
        ocrProgress.classList.add('active');
        ocrResult.style.display = 'none';
        ocrStatusText.textContent = 'Scanning document...';
        
        try {
            // Use Tesseract.js to OCR the image
            const result = await Tesseract.recognize(file, 'eng', {
                logger: m => {
                    if (m.status === 'recognizing text') {
                        const pct = Math.round((m.progress || 0) * 100);
                        ocrStatusText.textContent = `Scanning document... ${pct}%`;
                    }
                }
            });
            
            const text = result.data.text || '';
            console.log('OCR text:', text);
            
            // Extract PO number - look for patterns
            let poNumber = null;
            const poPatterns = [
                /(?:PO|P\.O\.?|Purchase\s*Order|Order\s*No\.?)\s*[#:]?\s*(\d{4,6})/i,
                /\b(2\d{4})\b/  // 5-digit numbers starting with 2 (like 20xxx)
            ];
            
            for (const pattern of poPatterns) {
                const match = text.match(pattern);
                if (match) {
                    poNumber = match[1];
                    break;
                }
            }
            
            // Extract other data
            const supplierMatch = text.match(/(?:Supplier|Vendor|From|Company)[:\s]+([A-Za-z][A-Za-z\s&'.,-]+)/i);
            const slipMatch = text.match(/(?:Packing\s*Slip|Slip\s*No|Docket\s*No|Invoice\s*No)[.:\s#]*(\S+)/i);
            const trackingMatch = text.match(/(?:Tracking|Consignment|AWB|Freight)[.:\s#]*(\S+)/i);
            const dateMatch = text.match(/(?:Date|Delivery\s*Date|Ship\s*Date)[.:\s]*(\d{1,2}[\/-]\d{1,2}[\/-]\d{2,4})/i);
            
            this.docketOCRData = {
                poNumber: poNumber,
                supplierName: supplierMatch ? supplierMatch[1].trim() : null,
                packingSlipNumber: slipMatch ? slipMatch[1].trim() : null,
                trackingNumber: trackingMatch ? trackingMatch[1].trim() : null,
                deliveryDate: dateMatch ? dateMatch[1].trim() : null,
                rawOcrText: text.substring(0, 2000)
            };
            
            ocrProgress.classList.remove('active');
            
            if (poNumber) {
                document.getElementById('po-number').value = poNumber;
                ocrResult.className = 'ocr-result found';
                ocrResult.innerHTML = `✅ Found PO #<strong>${poNumber}</strong>`;
                ocrResult.style.display = 'block';
            } else {
                ocrResult.className = 'ocr-result not-found';
                ocrResult.innerHTML = '⚠️ Could not find PO number — please enter manually';
                ocrResult.style.display = 'block';
            }
            
        } catch (error) {
            console.error('OCR error:', error);
            ocrProgress.classList.remove('active');
            ocrResult.className = 'ocr-result not-found';
            ocrResult.innerHTML = '⚠️ OCR failed — please enter PO number manually';
            ocrResult.style.display = 'block';
        }
    },
    
    // ============================================
    // Photo Mode Selection
    // ============================================
    setPhotoMode(mode) {
        this.photoMode = mode;
        
        // Update button styles
        document.querySelectorAll('.photo-mode-btn').forEach(btn => btn.classList.remove('active'));
        
        const groupSection = document.getElementById('group-photo-section');
        const individualSection = document.getElementById('individual-photo-section');
        const uploadNote = document.getElementById('photo-upload-note');
        
        groupSection.classList.add('hidden');
        individualSection.classList.add('hidden');
        
        if (mode === 'group') {
            document.getElementById('photo-mode-group').classList.add('active');
            groupSection.classList.remove('hidden');
            uploadNote.classList.remove('hidden');
        } else if (mode === 'individual') {
            document.getElementById('photo-mode-individual').classList.add('active');
            this.buildIndividualPhotoList();
            individualSection.classList.remove('hidden');
            uploadNote.classList.remove('hidden');
        } else {
            document.getElementById('photo-mode-skip').classList.add('active');
            uploadNote.classList.add('hidden');
            this.individualPhotos = [];
            this.evidencePhoto = null;
        }
    },

    buildIndividualPhotoList() {
        this.individualPhotos = [];
        const container = document.getElementById('individual-photo-list');
        
        container.innerHTML = this.selectedItems.map((item, index) => {
            return `
                <div class="individual-photo-item" id="photo-item-${index}">
                    <div class="photo-item-info">
                        <span class="photo-item-name">${item.description || 'Item ' + (index + 1)}</span>
                        <span class="photo-item-qty">Qty: ${item.quantity}</span>
                    </div>
                    <div class="photo-item-actions">
                        <div class="photo-item-capture" id="photo-capture-${index}">
                            <button class="btn btn-secondary btn-small" onclick="document.getElementById('photo-input-${index}').click()">
                                📷 Photo
                            </button>
                            <input type="file" accept="image/*" id="photo-input-${index}" hidden
                                onchange="app.handleIndividualPhoto(${index}, event)">
                        </div>
                        <div class="photo-item-preview hidden" id="photo-preview-${index}">
                            <img id="photo-img-${index}" src="" alt="Item photo" class="photo-thumbnail">
                            <button class="remove-photo-small" onclick="app.removeIndividualPhoto(${index})">✕</button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    },

    async handleIndividualPhoto(index, event) {
        const file = event.target.files[0];
        if (!file) return;
        
        try {
            const base64 = await this.compressImage(file);
            
            // Store photo
            const existing = this.individualPhotos.findIndex(p => p.itemIndex === index);
            const photoData = {
                itemIndex: index,
                description: this.selectedItems[index]?.description || 'Item',
                partNo: this.selectedItems[index]?.partNo || '',
                base64: base64
            };
            
            if (existing >= 0) {
                this.individualPhotos[existing] = photoData;
            } else {
                this.individualPhotos.push(photoData);
            }
            
            // Show preview
            document.getElementById(`photo-img-${index}`).src = base64;
            document.getElementById(`photo-preview-${index}`).classList.remove('hidden');
            document.getElementById(`photo-capture-${index}`).classList.add('hidden');
        } catch(e) { console.error("Photo compress error:", e); }
    },

    removeIndividualPhoto(index) {
        this.individualPhotos = this.individualPhotos.filter(p => p.itemIndex !== index);
        document.getElementById(`photo-preview-${index}`).classList.add('hidden');
        document.getElementById(`photo-capture-${index}`).classList.remove('hidden');
        document.getElementById(`photo-input-${index}`).value = '';
    },

    async handleEvidencePhoto(event) {
        const file = event.target.files[0];
        if (file) {
            try {
                const compressed = await this.compressImage(file);
                this.evidencePhoto = compressed;
                document.getElementById('evidence-img').src = compressed;
                document.getElementById('evidence-preview').classList.remove('hidden');
                document.getElementById('evidence-capture').classList.add('hidden');
            } catch(e) {
                const reader = new FileReader();
                reader.onload = (ev) => {
                    this.evidencePhoto = ev.target.result;
                    document.getElementById('evidence-img').src = ev.target.result;
                    document.getElementById('evidence-preview').classList.remove('hidden');
                    document.getElementById('evidence-capture').classList.add('hidden');
                };
                reader.readAsDataURL(file);
            }
        }
    },
    
    removeEvidencePhoto() {
        this.evidencePhoto = null;
        document.getElementById('evidence-preview').classList.add('hidden');
        document.getElementById('evidence-capture').classList.remove('hidden');
        document.getElementById('evidence-photo').value = '';
    },

    // ============================================
    // Image Compression Helper
    // ============================================
    compressImage(file, maxDim = 1200, quality = 0.7) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
                let w = img.width, h = img.height;
                if (w > maxDim || h > maxDim) {
                    if (w > h) { h = Math.round(h * maxDim / w); w = maxDim; }
                    else { w = Math.round(w * maxDim / h); h = maxDim; }
                }
                const canvas = document.createElement("canvas");
                canvas.width = w;
                canvas.height = h;
                const ctx = canvas.getContext("2d");
                ctx.drawImage(img, 0, 0, w, h);
                resolve(canvas.toDataURL("image/jpeg", quality));
            };
            img.onerror = reject;
            img.src = URL.createObjectURL(file);
        });
    },
    
    // ============================================
    // Labels
    // ============================================
    async printLabels() {
        const storageLocation = this.selectedStorage?.name || this._lastStorageName || 'Unknown';
        const poNumber = this.currentPO?.poNumber || 'N/A';
        const poJobNumber = this.currentPO?.jobNumber || '';
        const poCustomerName = this.currentPO?.customerName || '';
        
        const items = this.selectedItems.map(item => ({
            jobNumber: item.jobNumber || poJobNumber,
            customerName: item.customerName || poCustomerName,
            partNo: item.partNo || '',
            description: item.description,
            quantity: item.quantity,
            storageLocation: storageLocation
        }));
        
        await this.generateAndShowLabels(items, poNumber);
    },

    async generateAndShowLabels(items, poNumber) {
        // Generate PDF labels via server (QL-810W optimised)
        const today = new Date().toLocaleDateString('en-AU', { day: '2-digit', month: '2-digit', year: 'numeric' });
        
        const labels = [];
        for (const item of items) {
            const qty = item.quantity || 1;
            const jobNum = item.jobNumber ? `Job ${item.jobNumber}` : '';
            const customer = item.customerName || '';
            const partCode = item.partCode || item.catalogCode || item.partNo || '';
            const desc = item.description || item.name || '';
            const location = item.storageLocation || item.storageName || '';
            
            const line1 = [jobNum, customer].filter(Boolean).join(' \u00b7 ');
            const line2 = [partCode, desc].filter(Boolean).join(' \u00b7 ');
            const line3 = [`Qty: ${qty}`, location, today, `PO ${poNumber}`].filter(Boolean).join(' \u00b7 ');
            
            // One label per quantity
            for (let i = 0; i < qty; i++) {
                labels.push({ line1, line2, line3 });
            }
        }
        
        // Add filing label at the end (for job orders only, not stock)
        const filingJobNum = items.length > 0 ? (items[0].jobNumber || '') : '';
        if (filingJobNum && filingJobNum !== 'N/A' && filingJobNum !== 'Stock') {
            const filingCustomer = items[0].customerName || '';
            const filingLocation = items[0].storageLocation || items[0].storageName || '';
            labels.push({
                type: 'filing',
                line1: 'FILE: Job ' + filingJobNum + (poNumber && poNumber !== 'N/A' ? ' \u00b7 PO ' + poNumber : ''),
                line2: filingCustomer,
                line3: filingLocation ? ('>> ' + filingLocation) : ''
            });
        }
        
        if (labels.length === 0) {
            alert('No labels to print.');
            return;
        }
        
        try {
            // Pre-open window BEFORE async fetch - iOS Safari requires window.open
            // in the synchronous user gesture call stack (before any await)
            let pdfWindow = null;
            try {
                pdfWindow = window.open('about:blank', '_blank');
                if (pdfWindow) {
                    pdfWindow.document.write('<html><body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;color:#666;"><p>Generating labels...</p></body></html>');
                }
            } catch(e) { /* popup blocked - will use fallback */ }
            
            const response = await this.authFetch('/api/label-pdf', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.token}`
                },
                body: JSON.stringify({ labels })
            });
            
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || 'Failed to generate labels');
            }
            
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            
            // Redirect the pre-opened window to the PDF
            if (pdfWindow && !pdfWindow.closed) {
                pdfWindow.location.href = url;
            } else {
                // Fallback: try window.open (may work on desktop)
                const win = window.open(url, '_blank');
                if (!win) {
                    // Last resort: navigate current page briefly
                    window.location.href = url;
                }
            }
            
            // Clean up after a delay
            setTimeout(() => URL.revokeObjectURL(url), 60000);
            
        } catch (err) {
            // Close pre-opened window on error
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert('Label error: ' + err.message);
            console.error('Label PDF error:', err);
        }
    },
    

    // ============================================
    // Move Stock - Search by Job/PO
    // ============================================
    setRelocateMode(mode) {
        this.relocateMode = mode;
        
        // Toggle active button
        document.getElementById('relocate-mode-location').classList.toggle('active', mode === 'location');
        document.getElementById('relocate-mode-search').classList.toggle('active', mode === 'search');
        
        // Show/hide sections
        const locationMode = document.getElementById('relocate-location-mode');
        const searchMode = document.getElementById('relocate-search-mode');
        
        if (mode === 'location') {
            locationMode.classList.remove('hidden');
            searchMode.classList.add('hidden');
            document.getElementById('load-source-items-btn').style.display = '';
        } else {
            locationMode.classList.add('hidden');
            searchMode.classList.remove('hidden');
            // In search mode, the footer button text changes
            const btn = document.getElementById('load-source-items-btn');
            btn.style.display = 'none';
        }
    },
    
    updateSearchPlaceholder() {
        const searchType = document.querySelector('input[name="relocate-search-type"]:checked').value;
        const input = document.getElementById('relocate-search-input');
        input.placeholder = searchType === 'po' ? 'Enter PO number...' : 'Enter job number...';
    },
    
    async searchStockByJobPO() {
        const searchType = document.querySelector('input[name="relocate-search-type"]:checked').value;
        const searchValue = document.getElementById('relocate-search-input').value.trim();
        
        if (!searchValue) {
            this.showStatus('relocate-search-status', 'Please enter a number', 'error');
            return;
        }
        
        this.showStatus('relocate-search-status', 'Searching storage locations...', 'loading');
        document.getElementById('relocate-search-results').classList.add('hidden');
        document.getElementById('relocate-search-btn').disabled = true;
        
        try {
            const response = await this.authFetch('/api/stock-search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ searchType, searchValue })
            });
            
            const data = await response.json();
            
            if (data.error) {
                this.showStatus('relocate-search-status', data.error, 'error');
                document.getElementById('relocate-search-btn').disabled = false;
                return;
            }
            
            this.relocateSearchResults = data;
            this.relocateSearchPoId = searchValue;
            this.relocateMultiSource = true;
            this.relocateSelectedItems = [];
            
            // Show job info banner
            const banner = document.getElementById('relocate-search-job-info');
            if (data.job) {
                banner.innerHTML = '<div class="job-title">Job ' + (data.job.jobNumber || '') + '</div>' +
                    '<div class="job-detail">' + (data.job.customerName || '') + '</div>' +
                    '<div class="job-detail">' + data.pos.length + ' PO(s) | ' + (data.receivedCount || 0) + ' received | ' + (data.awaitingCount || 0) + ' awaiting receipt</div>';
                banner.classList.remove('hidden');
            } else {
                banner.classList.add('hidden');
            }
            
            if (data.items.length === 0) {
                this.showStatus('relocate-search-status', 'No items found in storage. Items may not be receipted yet or may have been dispatched.', 'error');
                document.getElementById('relocate-search-btn').disabled = false;
                return;
            }
            
            // Group items by storage location
            const groups = {};
            data.items.forEach((item, idx) => {
                const key = item.storageId;
                if (!groups[key]) {
                    groups[key] = {
                        storageId: item.storageId,
                        storageName: item.storageName,
                        items: []
                    };
                }
                groups[key].items.push({ ...item, globalIndex: idx });
            });
            
            // Render grouped items
            const listEl = document.getElementById('relocate-search-items-list');
            let html = '';
            
            Object.values(groups).forEach(group => {
                html += '<div class="location-group" data-storage-id="' + group.storageId + '">';
                html += '<div class="location-group-header">' +
                    '<span class="location-icon">📍</span>' +
                    '<span class="location-name">' + group.storageName + '</span>' +
                    '<span class="location-count">' + group.items.length + ' item' + (group.items.length > 1 ? 's' : '') + '</span>' +
                    '</div>';
                
                group.items.forEach(item => {
                    const isAwaiting = item.awaitingReceipt;
                    html += '<div class="item-card' + (isAwaiting ? ' awaiting-item' : '') + '" data-index="' + item.globalIndex + '">';
                    if (!isAwaiting) {
                        html += '<label class="item-checkbox">' +
                            '<input type="checkbox" onchange="app.toggleSearchItem(' + item.globalIndex + ')">' +
                            '<span class="checkmark"></span>' +
                            '</label>';
                    } else {
                        html += '<div class="awaiting-badge">\u23f3</div>';
                    }
                    html += '<div class="item-details">' +
                        '<div class="item-name">' + (item.description || 'Unknown Item') + '</div>' +
                        '<div class="item-meta">' +
                        (item.partNo ? '<span class="item-part">' + item.partNo + '</span>' : '') +
                        '<span class="item-qty">' + (isAwaiting ? 'Ordered: ' + item.quantityOrdered + ' (not received)' : 'Qty: ' + item.quantity) + '</span>' +
                        (item.poOrderNo ? '<span class="item-job">PO: ' + item.poOrderNo + '</span>' : '') +
                        '</div></div></div>';
                });
                
                html += '</div>';
            });
            
            listEl.innerHTML = html;
            
            // Hide status, show results
            document.getElementById('relocate-search-status').classList.add('hidden');
            document.getElementById('relocate-search-results').classList.remove('hidden');
            this.updateSearchSelectionCount();
            
        } catch (error) {
            console.error('Stock search error:', error);
            this.showStatus('relocate-search-status', 'Search failed: ' + error.message, 'error');
        }
        
        document.getElementById('relocate-search-btn').disabled = false;
    },
    

    async stockJobLookup() {
        const jobInput = document.getElementById('job-number');
        const jobNumber = jobInput ? jobInput.value.trim() : '';
        const resultsEl = document.getElementById('stock-results');
        
        if (!jobNumber) {
            resultsEl.innerHTML = '<p class="hint" style="color:#ef4444;">Please enter a job number</p>';
            return;
        }
        
        resultsEl.innerHTML = '<p class="hint">🔍 Looking up job ' + jobNumber + '...</p>';
        
        try {
            this._stockSearchMode = 'job';
            const response = await this.authFetch('/api/stock-search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ searchType: 'job', searchValue: jobNumber })
            });
            
            const data = await response.json();
            
            if (data.error) {
                resultsEl.innerHTML = '<p class="hint" style="color:#ef4444;">\u274c ' + data.error + '</p>';
                return;
            }
            
            let html = '';
            
            // Job info banner
            if (data.job) {
                html += '<div class="job-info-banner">';
                html += '<div class="job-title">Job ' + (data.job.jobNumber || jobNumber) + '</div>';
                html += '<div class="job-detail">' + (data.job.customerName || '') + '</div>';
                html += '<div class="job-detail">' + (data.receivedCount || 0) + ' received | ' + (data.awaitingCount || 0) + ' awaiting</div>';
                html += '</div>';
            }
            
            if (!data.items || data.items.length === 0) {
                html += '<p class="hint">No items found for this job</p>';
                resultsEl.innerHTML = html;
                return;
            }
            
            // Group by storage location
            const groups = {};
            data.items.forEach(item => {
                const key = item.storageId || 'awaiting';
                if (!groups[key]) {
                    groups[key] = {
                        storageName: item.awaitingReceipt ? '\u23f3 Awaiting Receipt' : (item.storageName || 'Unknown'),
                        items: [],
                        isAwaiting: item.awaitingReceipt
                    };
                }
                groups[key].items.push(item);
            });
            
            // Sort: received first, then awaiting
            const sortedGroups = Object.values(groups).sort((a, b) => (a.isAwaiting ? 1 : 0) - (b.isAwaiting ? 1 : 0));
            
            let globalIdx = 0;
            
            sortedGroups.forEach(group => {
                html += '<div class="location-group">';
                html += '<div class="location-group-header">';
                html += '<span class="location-icon">' + (group.isAwaiting ? '\u23f3' : '\ud83d\udccd') + '</span>';
                html += '<span class="location-name">' + group.storageName + '</span>';
                html += '<span class="location-count">' + group.items.length + ' item' + (group.items.length > 1 ? 's' : '') + '</span>';
                html += '</div>';
                
                group.items.forEach(item => {
                    if (item.awaitingReceipt) {
                        const awItemJson = JSON.stringify({
                            partNo: item.partNo || '',
                            description: item.description || '',
                            jobId: item.jobId || '',
                            jobNumber: item.jobNumber || jobNumber,
                            sectionId: item.sectionId || '',
                            costCentreId: item.costCentreId || '',
                            quantity: item.quantityOrdered || 0
                        }).replace(/'/g, '&#39;');
                        html += '<div class="item-card awaiting-item" style="border-left:3px solid #f59e0b;">';
                        html += '<div class="item-details" style="width:100%">';
                        html += '<div class="item-name">' + (item.description || 'Unknown') + ' <span style="font-size:11px;background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b44;border-radius:4px;padding:1px 5px;">⏳ Awaiting Receipt</span></div>';
                        html += '<div class="item-meta">';
                        if (item.partNo) html += '<span class="item-part">' + item.partNo + '</span>';
                        if (item.quantityOrdered) html += '<span class="item-qty">Ordered: ' + item.quantityOrdered + '</span>';
                        if (item.poOrderNo) html += '<span class="item-job">PO: ' + item.poOrderNo + '</span>';
                        html += '</div>';
                        const awData = JSON.stringify({
                            partNo: item.partNo || '',
                            description: item.description || '',
                            jobId: item.jobId || '',
                            jobNumber: item.jobNumber || jobNumber || '',
                            sectionId: item.sectionId || '',
                            costCentreId: item.costCentreId || '',
                            catalogId: item.catalogId || '',
                            quantity: item.quantityOrdered || 1
                        });
                        const awDataB64 = btoa(unescape(encodeURIComponent(awData)));
                        html += '<button onclick="app.showAwaitingAllocModal(\'' + awDataB64 + '\')" style="margin-top:8px;padding:6px 14px;background:#2563eb;color:#fff;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600;">📦 Allocate from Stock</button>';
                        html += '</div></div>';
                    } else {
                        const itemIdx = globalIdx++;
                        html += '<div class="item-card" onclick="app.toggleStockItem(' + itemIdx + ')" style="cursor:pointer;">';
                        html += '<div style="display:flex;align-items:center;gap:10px;width:100%">';
                        html += '<input type="checkbox" id="stock-cb-' + itemIdx + '" style="width:20px;height:20px;flex-shrink:0;" onclick="event.stopPropagation();" onchange="app.toggleStockItem(' + itemIdx + ')">';
                        html += '<div class="item-details" style="flex:1">';
                        html += '<div class="item-name">' + (item.description || 'Unknown') + '</div>';
                        html += '<div class="item-meta">';
                        if (item.partNo) html += '<span class="item-part">' + item.partNo + '</span>';
                        html += '<span class="item-qty">Qty: ' + item.quantity + '</span>';
                        if (item.poOrderNo) html += '<span class="item-job">PO: ' + item.poOrderNo + '</span>';
                        html += '</div></div></div></div>';
                    }
                });
                
                html += '</div>';
            });
            
            // Show message if all items are awaiting receipt (no clickable items)
            const allAwaiting = sortedGroups.length > 0 && sortedGroups.every(g => g.isAwaiting);
            if (allAwaiting) {
                html += '<p class="hint" style="color:#f59e0b;margin-top:12px;">⚠️ All items for this job are awaiting receipt — receive them via the PO receiving screen first.</p>';
            }
            
            resultsEl.innerHTML = html;
            
            // Store data for selection tracking
            this.stockSearchData = data;
            this.stockSelectedItems = [];
            // Build flat array of received items (matching globalIdx order)
            this._stockReceivedItems = [];
            const sortedGroupsCopy = Object.values(groups).sort((a, b) => (a.isAwaiting ? 1 : 0) - (b.isAwaiting ? 1 : 0));
            sortedGroupsCopy.forEach(g => {
                if (!g.isAwaiting) {
                    g.items.forEach(item => this._stockReceivedItems.push(item));
                }
            });
            document.getElementById('stock-action-panel').style.display = 'none';
            
        } catch (error) {
            console.error('Stock job lookup error:', error);
            resultsEl.innerHTML = '<p class="hint" style="color:#ef4444;">\u274c Search failed: ' + error.message + '</p>';
        }
    },
    
    async stockPartSearch() {
        const partInput = document.getElementById('part-search');
        const partNumber = partInput ? partInput.value.trim() : '';
        const resultsEl = document.getElementById('stock-results');
        
        if (!partNumber) {
            resultsEl.innerHTML = '<p class="hint" style="color:#ef4444;">Please enter a part number</p>';
            return;
        }
        
        resultsEl.innerHTML = '<p class="hint">\ud83d\udd0d Searching for ' + partNumber + '...</p>';
        
        try {
            const response = await this.authFetch('/api/stock-part-search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ partNumber: partNumber })
            });
            
            const data = await response.json();
            
            if (data.error) {
                resultsEl.innerHTML = '<p class="hint" style="color:#ef4444;">\u274c ' + data.error + '</p>';
                return;
            }
            
            if (!data.items || data.items.length === 0) {
                resultsEl.innerHTML = '<p class="hint">No stock found for part number "' + partNumber + '"</p>';
                return;
            }
            
            // Set part search mode
            this._stockSearchMode = 'part';
            this._partSearchItems = data.items;
            this.stockSelectedItems = [];
            this.stockSearchData = null;
            
            let html = '<div class="job-info-banner"><div class="job-title">\ud83d\udd0d Part Search: ' + partNumber + '</div>';
            html += '<div class="job-detail">' + data.items.length + ' location(s) found</div></div>';
            
            data.items.forEach((item, idx) => {
                html += '<div class="item-card" onclick="app.toggleStockItem(' + idx + ')" style="cursor:pointer;">';
                html += '<div style="display:flex;align-items:center;gap:10px;width:100%">';
                html += '<input type="checkbox" id="stock-cb-' + idx + '" style="width:20px;height:20px;flex-shrink:0;" onclick="event.stopPropagation();" onchange="app.toggleStockItem(' + idx + ')">';
                html += '<div class="item-details" style="flex:1">';
                html += '<div class="item-name">' + (item.description || item.partNo || 'Unknown') + '</div>';
                html += '<div class="item-meta">';
                html += '<span class="item-part">' + (item.partNo || '') + '</span>';
                html += '<span class="item-qty">Qty: ' + (item.quantity || 0) + '</span>';
                html += '<span class="location-name">\ud83d\udccd ' + (item.storageName || 'Unknown') + '</span>';
                html += '</div></div></div></div>';
            });
            
            resultsEl.innerHTML = html;
            document.getElementById('stock-action-panel').style.display = 'none';
            
        } catch (error) {
            console.error('Part search error:', error);
            resultsEl.innerHTML = '<p class="hint" style="color:#ef4444;">\u274c Search failed: ' + error.message + '</p>';
        }
    },
    
    showAwaitingTip() {
        // Show a brief toast instead of an alert
        const existing = document.getElementById('awaiting-toast');
        if (existing) return;
        const toast = document.createElement('div');
        toast.id = 'awaiting-toast';
        toast.style.cssText = 'position:fixed;bottom:120px;left:50%;transform:translateX(-50%);background:#f59e0b;color:#000;padding:10px 18px;border-radius:20px;font-size:14px;font-weight:600;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,0.3);pointer-events:none;';
        toast.textContent = '⏳ Not received yet — receive via PO screen first';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2500);
    },

    navigateToStockSearch(partNo, description, jobId, jobNumber, sectionId, costCentreId, quantity) {
        // Store job context for pre-fill during allocation step
        this._pendingJobContext = {
            partNo: partNo,
            description: description,
            jobId: jobId,
            jobNumber: jobNumber,
            sectionId: sectionId,
            costCentreId: costCentreId,
            quantity: quantity
        };
        
        // Navigate to stock screen
        this.showScreen('stock');
        
        // Switch to part search mode by clicking the Part Search tab if it exists
        const partTab = document.getElementById('tab-part-search') || document.querySelector('[data-tab="part-search"]') || document.querySelector('.tab-btn[onclick*="part"]');
        if (partTab) partTab.click();
        
        // Pre-fill part search input
        const partInput = document.getElementById('part-search');
        if (partInput && partNo) {
            partInput.value = partNo;
        }
        
        // Also pre-fill job number input if it exists on the stock screen
        const jobInput = document.getElementById('stock-job-number') || document.getElementById('allocate-job-number');
        if (jobInput && jobNumber) {
            jobInput.value = jobNumber;
        }
        
        // Auto-trigger part search after a short delay
        setTimeout(() => {
            if (partNo) {
                this.stockPartSearch();
            }
        }, 100);
        
        // Show a status hint
        setTimeout(() => {
            const resultsEl = document.getElementById('stock-results');
            if (resultsEl && this._stockSearchMode === 'part') {
                // After search runs, show a job context banner if results present
                const existingBanner = resultsEl.querySelector('.pending-job-banner');
                if (!existingBanner && jobNumber) {
                    const banner = document.createElement('div');
                    banner.className = 'pending-job-banner';
                    banner.style.cssText = 'background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:8px 12px;margin-bottom:8px;font-size:13px;color:#1e40af;';
                    banner.innerHTML = '📋 Allocating to Job <strong>' + jobNumber + '</strong>' + (description ? ' — ' + description : '') + (quantity ? ' (need: ' + quantity + ')' : '');
                    resultsEl.insertBefore(banner, resultsEl.firstChild);
                }
            }
        }, 500);
    },

    toggleStockItem(index) {
        const cb = document.getElementById('stock-cb-' + index);
        const idx = this.stockSelectedItems.indexOf(index);
        if (idx >= 0) {
            this.stockSelectedItems.splice(idx, 1);
            if (cb) cb.checked = false;
        } else {
            this.stockSelectedItems.push(index);
            if (cb) cb.checked = true;
        }
        // Show/hide action panel
        const panel = document.getElementById('stock-action-panel');
        const countEl = document.getElementById('stock-item-count');
        const jobGroup = document.getElementById('stock-target-job-group');
        if (this.stockSelectedItems.length > 0) {
            panel.style.display = 'block';
            countEl.textContent = this.stockSelectedItems.length;
            // Show job input for part search mode, hide for job mode
            if (jobGroup) {
                jobGroup.style.display = (this._stockSearchMode === 'part') ? 'block' : 'none';
            }
        } else {
            panel.style.display = 'none';
        }
    },
    
    async allocateFromStock() {
        const destDropdown = document.getElementById('stock-storage-dropdown');
        const destId = destDropdown.value;
        const destName = destDropdown.options[destDropdown.selectedIndex]?.text || '';
        
        if (!destId) {
            alert('Please select a destination storage location.');
            return;
        }
        
        if (this.stockSelectedItems.length === 0) {
            alert('Please select at least one item.');
            return;
        }
        
        const isPartSearch = (this._stockSearchMode === 'part');
        let targetJobId = '';
        let jobNumber = '';
        let customerName = '';
        
        if (isPartSearch) {
            const jobInput = document.getElementById('stock-target-job');
            // Pre-fill from pending job context if available and input is empty
            if (this._pendingJobContext && jobInput && !jobInput.value && this._pendingJobContext.jobNumber) {
                jobInput.value = this._pendingJobContext.jobNumber;
            }
            targetJobId = jobInput ? jobInput.value.trim() : '';
            if (!targetJobId) {
                alert('Please enter a Job number to allocate stock to.');
                return;
            }
            jobNumber = targetJobId;
        } else {
            jobNumber = this.stockSearchData?.job?.jobNumber || '';
            customerName = this.stockSearchData?.job?.customerName || '';
        }
        
        // Build items array from selected indices
        const sourceItems = isPartSearch ? this._partSearchItems : this._stockReceivedItems;
        const items = this.stockSelectedItems.map(idx => {
            const item = sourceItems[idx];
            return {
                catalogId: item.catalogId,
                partNo: item.partNo,
                description: item.description,
                quantity: item.quantity,
                sourceId: item.storageId,
                sourceName: item.storageName,
                jobId: item.jobId || null,
                sectionId: item.sectionId || null,
                costCentreId: item.costCentreId || null,
                poOrderNo: item.poOrderNo || ''
            };
        });
        
        // If part search with target job: do CC confirmation first
        if (isPartSearch && targetJobId) {
            await this.doJobCCLookup(targetJobId, destId, destName, items, jobNumber);
            return;
        }
        
        // Non-part-search (job mode): items already have jobId/sectionId/costCentreId from search
        await this.doDirectAllocation(destId, destName, items, jobNumber, customerName, '');
    },
    
    async doJobCCLookup(targetJobId, destId, destName, items, jobNumber) {
        const btn = document.getElementById('stock-allocate-btn');
        btn.disabled = true;
        btn.textContent = '\u23f3 Looking up job cost centres...';
        
        // Remove any existing CC panel
        const existing = document.getElementById('cc-confirm-panel');
        if (existing) existing.remove();
        
        try {
            // Use first item for lookup
            const firstItem = items[0];
            const lookupPayload = {
                jobId: parseInt(targetJobId),
                catalogId: firstItem.catalogId,
                partNo: firstItem.partNo,
                description: firstItem.description
            };
            
            const response = await this.authFetch('/api/job-cc-lookup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(lookupPayload)
            });
            
            const data = await response.json();
            
            if (data.error) {
                alert('CC Lookup error: ' + data.error);
                btn.disabled = false;
                btn.textContent = '\ud83d\udce6 Move & Print Labels';
                return;
            }
            
            btn.disabled = false;
            btn.textContent = '\ud83d\udce6 Move & Print Labels';
            
            this.showCCConfirmPanel(data, targetJobId, destId, destName, items, jobNumber);
            
        } catch (error) {
            console.error('CC lookup error:', error);
            alert('Error looking up cost centres: ' + error.message);
            btn.disabled = false;
            btn.textContent = '\ud83d\udce6 Move & Print Labels';
        }
    },
    
    showCCConfirmPanel(data, targetJobId, destId, destName, items, jobNumber) {
        const actionPanel = document.getElementById('stock-action-panel');
        
        // Remove any existing CC panel
        const existing = document.getElementById('cc-confirm-panel');
        if (existing) existing.remove();
        
        const job = data.job || {};
        const matches = data.matches || [];
        const notFound = data.notFound;
        
        const firstItem = items[0];
        
        let html = '<div id="cc-confirm-panel" style="margin-top:16px; border:2px solid #22d3ee; border-radius:10px; padding:14px; background:#0f172a;">';
        html += '<div style="font-size:13px; font-weight:600; color:#22d3ee; margin-bottom:10px; border-bottom:1px solid #334155; padding-bottom:8px;">── Confirm Job Cost Centre ──</div>';
        
        // Job info
        html += '<div style="font-size:13px; color:#94a3b8; margin-bottom:8px;">';
        html += '<strong style="color:#e2e8f0;">Job: ' + (job.name || targetJobId) + '</strong>';
        if (job.customer) html += ' &nbsp;|&nbsp; ' + job.customer;
        if (job.site) html += '<br><span style="font-size:12px;">' + job.site + '</span>';
        html += '</div>';
        
        // Selected items
        html += '<div style="font-size:12px; color:#94a3b8; margin-bottom:10px;">';
        items.forEach(item => {
            html += '<div>\u25cf ' + (item.description || item.partNo) + (item.partNo ? ' (' + item.partNo + ')' : '') + ' &times;' + item.quantity + '</div>';
        });
        html += '</div>';
        
        if (notFound) {
            // Item not on job
            html += '<div style="background:#7c3d00; border:1px solid #f59e0b; border-radius:8px; padding:10px; margin-bottom:12px; color:#fef3c7; font-size:13px;">';
            html += '\u26a0\ufe0f Item not found on this job\'s material list';
            html += '</div>';
            
            html += '<button onclick="app.showManualAllocConfirm(\'' + targetJobId + '\', \'' + (job.name || targetJobId).replace(/'/g, '') + '\', \'' + destId + '\', \'' + destName.replace(/'/g, '') + '\', app._pendingCCItems)" style="width:100%; padding:12px; border-radius:8px; background:#f59e0b; color:#000; font-weight:600; border:none; cursor:pointer; margin-bottom:8px; font-size:14px;">Add to Job after Confirmation</button>';
            html += '<button onclick="app.cancelCCConfirm()" style="width:100%; padding:10px; border-radius:8px; background:#334155; color:#e2e8f0; font-weight:500; border:none; cursor:pointer; font-size:14px;">Cancel</button>';
            
        } else {
            // Show matching CCs
            html += '<div style="font-size:13px; color:#94a3b8; margin-bottom:8px;">Matching job material lines:</div>';
            
            matches.forEach((m, idx) => {
                const storeLocs = m.storageLocations.map(s => s.name + ' (\u00d7' + s.qty + ')').join(', ');
                html += '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:10px;padding:8px;border:1px solid #334155;border-radius:8px;">';
                html += '<input type="radio" name="cc-choice" value="' + idx + '" id="cc-r-' + idx + '" style="margin-top:3px;flex-shrink:0;" ' + (idx === 0 ? 'checked' : '') + '>';
                html += '<label for="cc-r-' + idx + '" style="cursor:pointer;flex:1;">';
                html += '<div style="font-size:13px; color:#e2e8f0; font-weight:500;">' + m.costCentreName + '</div>';
                if (m.sectionName && m.sectionName !== m.costCentreName) {
                    html += '<div style="font-size:12px; color:#64748b;">Section: ' + m.sectionName + '</div>';
                }
                html += '<div style="font-size:12px; color:#94a3b8; margin-top:3px;">';
                html += 'Required: ' + m.requiredQty + ' &nbsp; Allocated: ' + m.assignedQty + ' &nbsp; Remaining: ' + m.remainingQty;
                html += '</div>';
                if (storeLocs) {
                    html += '<div style="font-size:12px; color:#64748b;">Currently in: ' + storeLocs + '</div>';
                }
                html += '</label>';
                html += '</div>';
            });
            
            // Source/dest info
            const firstItem = items[0];
            html += '<div style="font-size:12px; color:#64748b; margin-bottom:10px;">';
            html += 'Source: ' + (firstItem.sourceName || 'Unknown') + ' &rarr; Destination: ' + destName;
            html += '</div>';
            
            html += '<button onclick="app.doAllocateWithSelectedCC(\'' + targetJobId + '\', \'' + destId + '\', \'' + destName.replace(/'/g, '') + '\', app._pendingCCItems, app._pendingCCMatches, \'' + (job.customer || '').replace(/'/g, '') + '\', \'' + (job.name || '').replace(/'/g, '') + '\')" style="width:100%; padding:12px; border-radius:8px; background:#22d3ee; color:#000; font-weight:600; border:none; cursor:pointer; margin-bottom:8px; font-size:14px;">\u2705 Allocate to Selected Cost Centre</button>';
            html += '<button onclick="app.cancelCCConfirm()" style="width:100%; padding:10px; border-radius:8px; background:#334155; color:#e2e8f0; font-weight:500; border:none; cursor:pointer; font-size:14px;">Cancel</button>';
        }
        
        html += '</div>';
        
        // Store pending data
        this._pendingCCItems = items;
        this._pendingCCMatches = matches;
        
        // Insert CC panel after the allocate button
        const allocBtn = document.getElementById('stock-allocate-btn');
        allocBtn.insertAdjacentHTML('afterend', html);
        
        // Scroll to panel
        setTimeout(() => {
            document.getElementById('cc-confirm-panel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 100);
    },
    
    cancelCCConfirm() {
        const panel = document.getElementById('cc-confirm-panel');
        if (panel) panel.remove();
    },
    
    async doAllocateWithSelectedCC(targetJobId, destId, destName, items, matches, customerName, jobName) {
        // Get selected CC radio
        const selected = document.querySelector('input[name="cc-choice"]:checked');
        const matchIdx = selected ? parseInt(selected.value) : 0;
        const match = matches[matchIdx];
        
        if (!match) {
            alert('Please select a cost centre.');
            return;
        }
        
        // Add confirmed section/CC to each item
        const confirmedItems = items.map(item => ({
            ...item,
            sectionId: match.sectionId,
            costCentreId: match.costCentreId
        }));
        
        // Remove CC panel
        document.getElementById('cc-confirm-panel')?.remove();
        
        await this.doDirectAllocation(
            destId, destName, confirmedItems, 
            jobName || targetJobId, customerName, targetJobId
        );
    },
    
    showManualAllocConfirm(targetJobId, jobName, destId, destName, items) {
        const panel = document.getElementById('cc-confirm-panel');
        const noteText = 'Stock manually adjusted and allocated to Job ' + targetJobId + '. Item was physically available but not showing as available stock in Simpro.';
        
        let html = '<div id="cc-confirm-panel" style="margin-top:16px; border:2px solid #f59e0b; border-radius:10px; padding:14px; background:#0f172a;">';
        html += '<div style="font-size:13px; font-weight:600; color:#f59e0b; margin-bottom:10px;">\u26a0\ufe0f Manual Stock Adjustment</div>';
        html += '<div style="font-size:13px; color:#94a3b8; margin-bottom:12px; line-height:1.5;">';
        html += 'This item is not on the job\'s material list. Allocating anyway will create a manual stock adjustment.<br><br>';
        html += '<strong style="color:#e2e8f0;">A note will be added to the job:</strong><br>';
        html += '<em style="color:#94a3b8;">"' + noteText + '"</em>';
        html += '</div>';
        html += '<button onclick="app.doManualAllocation(\'' + targetJobId + '\', \'' + destId + '\', \'' + destName.replace(/'/g, '') + '\', app._pendingCCItems, \'' + noteText.replace(/'/g, '') + '\')" style="width:100%; padding:12px; border-radius:8px; background:#f59e0b; color:#000; font-weight:600; border:none; cursor:pointer; margin-bottom:8px; font-size:14px;">Confirm Manual Allocation</button>';
        html += '<button onclick="app.cancelCCConfirm()" style="width:100%; padding:10px; border-radius:8px; background:#334155; color:#e2e8f0; font-weight:500; border:none; cursor:pointer; font-size:14px;">Cancel</button>';
        html += '</div>';
        
        if (panel) {
            panel.outerHTML = html;
        } else {
            const allocBtn = document.getElementById('stock-allocate-btn');
            allocBtn.insertAdjacentHTML('afterend', html);
        }
    },
    
    async doManualAllocation(targetJobId, destId, destName, items, noteText) {
        const btn = document.getElementById('stock-allocate-btn');
        btn.disabled = true;
        btn.textContent = '\u23f3 Moving items...';
        document.getElementById('cc-confirm-panel')?.remove();
        
        try {
            // Simple stock transfer (no job allocation - item not on job)
            const payload = {
                destId: parseInt(destId),
                destName: destName,
                jobNumber: targetJobId,
                customerName: '',
                items: items
                // No targetJobId - simple transfer only
            };
            
            const response = await this.authFetch('/api/allocate-from-stock', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const result = await response.json();
            
            // Add job note regardless of transfer result
            try {
                await this.authFetch('/api/job-note', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ jobId: parseInt(targetJobId), note: noteText })
                });
            } catch (noteErr) {
                console.warn('Note error:', noteErr);
            }
            
            const successCount = result.results ? result.results.filter(r => r.success).length : 0;
            
            if (successCount > 0) {
                const successItems = [];
                for (const r of result.results) {
                    if (r.success) {
                        const origItem = items.find(i => String(i.catalogId) === String(r.catalogId));
                        if (origItem) {
                            successItems.push({
                                jobNumber: targetJobId,
                                customerName: '',
                                partNo: origItem.partNo,
                                description: origItem.description,
                                quantity: origItem.quantity,
                                storageLocation: destName
                            });
                        }
                    }
                }
                const poNumber = items[0]?.poOrderNo || 'Stock';
                await this.generateAndShowLabels(successItems, poNumber);
            }
            
            let msg = '\u2705 ' + successCount + ' item(s) moved to ' + destName;
            msg += '\n\ud83d\udcdd Note added to Job ' + targetJobId;
            alert(msg);
            
            this.stockSelectedItems = [];
            document.getElementById('stock-action-panel').style.display = 'none';
            this.stockPartSearch();
            
        } catch (error) {
            console.error('Manual allocation error:', error);
            alert('Error: ' + error.message);
        } finally {
            btn.disabled = false;
            btn.textContent = '\ud83d\udce6 Move & Print Labels';
        }
    },
    
    async doDirectAllocation(destId, destName, items, jobNumber, customerName, targetJobId) {
        const btn = document.getElementById('stock-allocate-btn');
        btn.disabled = true;
        btn.textContent = '\u23f3 Moving items...';
        
        try {
            const payload = {
                destId: parseInt(destId),
                destName: destName,
                jobNumber: jobNumber,
                customerName: customerName,
                items: items
            };
            if (targetJobId) {
                payload.targetJobId = targetJobId;
            }
            
            const response = await this.authFetch('/api/allocate-from-stock', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const result = await response.json();
            
            if (result.error) {
                alert('Error: ' + result.error);
                return;
            }
            
            if (result.customerName) customerName = result.customerName;
            if (result.jobNumber) jobNumber = result.jobNumber;
            
            const successCount = result.results ? result.results.filter(r => r.success).length : 0;
            const failCount = result.results ? result.results.filter(r => !r.success).length : 0;
            
            if (successCount > 0) {
                const successItems = [];
                for (const r of result.results) {
                    if (r.success) {
                        const origItem = items.find(i => String(i.catalogId) === String(r.catalogId));
                        if (origItem) {
                            successItems.push({
                                jobNumber: jobNumber,
                                customerName: customerName,
                                partNo: origItem.partNo,
                                description: origItem.description,
                                quantity: origItem.quantity,
                                storageLocation: destName
                            });
                        }
                    }
                }
                const poNumber = items[0]?.poOrderNo || 'Stock';
                await this.generateAndShowLabels(successItems, poNumber);
            }
            
            let msg = '\u2705 ' + successCount + ' item(s) moved to ' + destName;
            if (jobNumber) msg += ' for Job ' + jobNumber;
            if (failCount > 0) {
                msg += '\n\u26a0\ufe0f ' + failCount + ' item(s) failed:';
                result.results.filter(r => !r.success).forEach(r => {
                    msg += '\n  - ' + r.partNo + ': ' + (r.error || 'Unknown error');
                });
            }
            alert(msg);
            
            this.stockSelectedItems = [];
            document.getElementById('stock-action-panel').style.display = 'none';
            document.getElementById('cc-confirm-panel')?.remove();
            if (this._stockSearchMode === 'part') {
                this.stockPartSearch();
            } else {
                this.stockJobLookup();
            }
            
        } catch (error) {
            console.error('Allocation error:', error);
            alert('Error: ' + error.message);
        } finally {
            btn.disabled = false;
            btn.textContent = '\ud83d\udce6 Move & Print Labels';
        }
    },
    
    toggleSearchItem(globalIndex) {
        const items = this.relocateSearchResults.items;
        const item = items[globalIndex];
        const idx = this.relocateSelectedItems.findIndex(i => i.globalIndex === globalIndex);
        
        if (idx >= 0) {
            this.relocateSelectedItems.splice(idx, 1);
        } else {
            this.relocateSelectedItems.push({
                globalIndex,
                catalogId: item.catalogId,
                partNo: item.partNo,
                description: item.description,
                quantity: item.quantity,
                storageId: item.storageId,
                storageName: item.storageName,
                poOrderNo: item.poOrderNo,
                jobId: item.jobId || null,
                sectionId: item.sectionId || null,
                costCentreId: item.costCentreId || null
            });
        }
        
        this.updateSearchSelectionCount();
    },
    
    updateSearchSelectionCount() {
        const count = this.relocateSelectedItems.length;
        const total = this.relocateSearchResults ? this.relocateSearchResults.items.length : 0;
        document.getElementById('relocate-search-selection-count').textContent = 
            count + ' of ' + total + ' items selected';
        
        // Show/enable a "Move Selected" button in the footer
        let moveBtn = document.getElementById('search-move-btn');
        if (!moveBtn) {
            const footer = document.querySelector('#screen-relocate-source footer');
            moveBtn = document.createElement('button');
            moveBtn.id = 'search-move-btn';
            moveBtn.className = 'btn btn-primary btn-large';
            moveBtn.textContent = 'Move Selected \u2192';
            moveBtn.onclick = () => this.showSearchDestScreen();
            footer.appendChild(moveBtn);
        }
        moveBtn.style.display = count > 0 ? '' : 'none';
        moveBtn.textContent = 'Move ' + count + ' Item' + (count !== 1 ? 's' : '') + ' \u2192';
    },
    
    showSearchDestScreen() {
        if (this.relocateSelectedItems.length === 0) return;
        
        // Count unique sources
        const sources = {};
        this.relocateSelectedItems.forEach(item => {
            sources[item.storageId] = item.storageName;
        });
        const sourceCount = Object.keys(sources).length;
        const sourceNames = Object.values(sources).join(', ');
        
        document.getElementById('relocate-dest-item-count').textContent = this.relocateSelectedItems.length;
        const fromInfo = document.getElementById('relocate-from-info');
        if (fromInfo) {
            if (sourceCount === 1) {
                fromInfo.innerHTML = 'from <strong id="relocate-from-name">' + sourceNames + '</strong>';
            } else {
                fromInfo.innerHTML = 'from <strong id="relocate-from-name">' + sourceCount + ' locations</strong>';
            }
        }
        
        document.getElementById('relocate-dest-dropdown').value = '';
        document.getElementById('execute-relocate-btn').disabled = true;
        document.getElementById('relocate-dest-warning').classList.add('hidden');
        
        this.showScreen('relocate-dest');
    },

    // ============================================
    // Relocate Stock - By Location
    // ============================================
    selectRelocateSource(event) {
        const select = event.target;
        const selectedOption = select.options[select.selectedIndex];
        
        if (select.value) {
            this.relocateSourceId = parseInt(select.value);
            this.relocateSourceName = selectedOption.textContent;
            document.getElementById('load-source-items-btn').disabled = false;
        } else {
            this.relocateSourceId = null;
            this.relocateSourceName = null;
            document.getElementById('load-source-items-btn').disabled = true;
        }
    },
    
    async loadRelocateItems() {
        if (!this.relocateSourceId) return;
        
        this.showStatus('relocate-source-status', 'Loading items from storage...', 'loading');
        
        try {
            const response = await fetch(`/api/storage/${this.relocateSourceId}/stock`);
            const data = await response.json();
            
            if (data.error) {
                this.showStatus('relocate-source-status', data.error, 'error');
                return;
            }
            
            this.relocateItems = data.items || [];
            this.relocateSelectedItems = [];
            
            if (this.relocateItems.length === 0) {
                this.showStatus('relocate-source-status', 'No items found in this location', 'error');
                return;
            }
            
            this.showRelocateItemsScreen();
            
        } catch (error) {
            console.error('Load storage items error:', error);
            this.showStatus('relocate-source-status', 'Failed to load items', 'error');
        }
    },
    
    showRelocateItemsScreen() {
        document.getElementById('relocate-source-title').textContent = `From: ${this.relocateSourceName}`;
        document.getElementById('relocate-item-count-info').textContent = `${this.relocateItems.length} item(s) in location`;
        
        const itemsList = document.getElementById('relocate-items-list');
        
        itemsList.innerHTML = this.relocateItems.map((item, index) => {
            return `
                <div class="item-card" data-index="${index}">
                    <label class="item-checkbox">
                        <input type="checkbox" onchange="app.toggleRelocateItem(${index})">
                        <span class="checkmark"></span>
                    </label>
                    <div class="item-details">
                        <div class="item-name">${item.description || item.name || 'Unknown Item'}</div>
                        <div class="item-meta">
                            ${item.partNo ? `<span class="item-part">${item.partNo}</span>` : ''}
                            <span class="item-qty">Qty: ${item.quantity}</span>
                            ${item.jobNumber ? `<span class="item-job">Job: ${item.jobNumber}</span>` : ''}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
        
        this.updateRelocateSelectionCount();
        this.showScreen('relocate-items');
    },
    
    toggleRelocateItem(index) {
        const item = this.relocateItems[index];
        const idx = this.relocateSelectedItems.findIndex(i => i.index === index);
        
        if (idx >= 0) {
            this.relocateSelectedItems.splice(idx, 1);
        } else {
            this.relocateSelectedItems.push({
                index,
                ...item
            });
        }
        
        this.updateRelocateSelectionCount();
    },
    
    toggleRelocateSelectAll(event) {
        const checked = event.target.checked;
        const checkboxes = document.querySelectorAll('#relocate-items-list input[type="checkbox"]');
        
        this.relocateSelectedItems = [];
        
        checkboxes.forEach((cb, index) => {
            cb.checked = checked;
            if (checked && this.relocateItems[index]) {
                this.relocateSelectedItems.push({
                    index,
                    ...this.relocateItems[index]
                });
            }
        });
        
        this.updateRelocateSelectionCount();
    },
    
    updateRelocateSelectionCount() {
        const count = this.relocateSelectedItems.length;
        const total = this.relocateItems.length;
        
        document.getElementById('relocate-selection-count').textContent = `${count} of ${total} items selected`;
        document.getElementById('to-relocate-dest-btn').disabled = count === 0;
    },
    
    showRelocateDestScreen() {
        document.getElementById('relocate-dest-item-count').textContent = this.relocateSelectedItems.length;
        document.getElementById('relocate-from-name').textContent = this.relocateSourceName;
        document.getElementById('relocate-dest-dropdown').value = '';
        document.getElementById('execute-relocate-btn').disabled = true;
        document.getElementById('relocate-dest-warning').classList.add('hidden');
        
        this.showScreen('relocate-dest');
    },
    
    selectRelocateDest(event) {
        const select = event.target;
        const selectedOption = select.options[select.selectedIndex];
        
        if (select.value) {
            const destId = parseInt(select.value);
            
            // Check if same as source
            const sourceIds = this.relocateMultiSource 
                ? [...new Set(this.relocateSelectedItems.map(i => i.storageId))]
                : [this.relocateSourceId];
            if (sourceIds.includes(destId) && sourceIds.length === 1) {
                document.getElementById('relocate-dest-warning').classList.remove('hidden');
                document.getElementById('execute-relocate-btn').disabled = true;
                return;
            }
            
            document.getElementById('relocate-dest-warning').classList.add('hidden');
            this.relocateDestId = destId;
            this.relocateDestName = selectedOption.textContent;
            document.getElementById('execute-relocate-btn').disabled = false;
        } else {
            this.relocateDestId = null;
            this.relocateDestName = null;
            document.getElementById('execute-relocate-btn').disabled = true;
        }
    },
    
    async executeRelocate() {
        if (!this.relocateDestId || this.relocateSelectedItems.length === 0) {
            alert('Please select items and a destination');
            return;
        }
        
        this.showScreen('processing');
        document.getElementById('processing-status').textContent = 'Relocating items...';
        document.getElementById('processing-detail').textContent = `Moving to ${this.relocateDestName}`;
        
        try {
            if (this.relocateMultiSource) {
                // Group items by source storage
                const groups = {};
                this.relocateSelectedItems.forEach(item => {
                    const key = item.storageId;
                    if (!groups[key]) {
                        groups[key] = {
                            sourceId: item.storageId,
                            sourceName: item.storageName,
                            items: []
                        };
                    }
                    groups[key].items.push({
                        catalogId: item.catalogId,
                        quantity: item.quantity,
                        partNo: item.partNo || '',
                        description: item.description || '',
                        jobId: item.jobId || null,
                        sectionId: item.sectionId || null,
                        costCentreId: item.costCentreId || null
                    });
                });
                
                let totalSuccess = 0;
                let totalFailed = 0;
                let lastData = null;
                const groupList = Object.values(groups);
                const filteredGroups = groupList.filter(g => String(g.sourceId) !== String(this.relocateDestId));
                const skippedCount = groupList.reduce((sum, g) => 
                    String(g.sourceId) === String(this.relocateDestId) ? sum + g.items.length : sum, 0);
                
                if (filteredGroups.length === 0) {
                    alert('All selected items are already at that destination.');
                    this.showScreen('relocate-dest');
                    return;
                }
                
                for (let i = 0; i < filteredGroups.length; i++) {
                    const group = filteredGroups[i];
                    document.getElementById('processing-detail').textContent = 
                        `Moving from ${group.sourceName} (${i + 1}/${filteredGroups.length})`;
                    
                    const response = await this.authFetch('/api/stock-move', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            poId: this.relocateSearchPoId,
                            sourceId: group.sourceId,
                            sourceName: group.sourceName,
                            destId: this.relocateDestId,
                            destName: this.relocateDestName,
                            items: group.items
                        })
                    });
                    
                    const data = await response.json();
                    lastData = data;
                    
                    if (data.successCount > 0) {
                        totalSuccess += data.successCount;
                        totalFailed += (data.totalItems - data.successCount);
                    } else if (data.error) {
                        totalFailed += group.items.length;
                    } else {
                        totalFailed += group.items.length;
                    }
                }
                
                if (totalSuccess > 0) {
                    // Build multi-source success
                    const sourceNames = filteredGroups.map(g => g.sourceName).join(', ');
                    this.relocateSourceName = sourceNames;
                    this.showRelocateSuccess({
                        success: true,
                        successCount: totalSuccess,
                        failedCount: totalFailed,
                        skippedCount: skippedCount
                    });
                } else {
                    alert('Relocation failed - no items could be moved. Items may have already been moved or are no longer at the expected location.');
                    this.showScreen('relocate-dest');
                }
            } else {
                // Original single-source flow
                const response = await this.authFetch('/api/relocate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sourceId: this.relocateSourceId,
                        sourceName: this.relocateSourceName,
                        destId: this.relocateDestId,
                        destName: this.relocateDestName,
                        items: this.relocateSelectedItems.map(item => ({
                            stockId: item.stockId,
                            catalogId: item.catalogId,
                            quantity: item.quantity,
                            partNo: item.partNo || '',
                            description: item.description || item.name,
                            jobId: item.jobId
                        }))
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    this.showRelocateSuccess(data);
                } else {
                    alert('Relocation failed: ' + (data.error || 'Unknown error'));
                    this.showScreen('relocate-dest');
                }
            }
        } catch (error) {
            console.error('Relocate error:', error);
            alert('Relocation failed: ' + error.message);
            this.showScreen('relocate-dest');
        }
    },
    
    showRelocateSuccess(data) {
        // Handle queued response (browser automation required)
        if (data.requiresBrowserAutomation) {
            document.getElementById('relocate-success-summary').textContent = 
                `${data.queuedCount || this.relocateSelectedItems.length} item(s) queued for transfer`;
            document.getElementById('relocate-success-from').textContent = `From: ${this.relocateSourceName}`;
            document.getElementById('relocate-success-to').textContent = `To: ${this.relocateDestName}`;
            document.getElementById('relocate-staff-name').textContent = this.currentStaff?.displayName || 'Staff';
            
            // Add note about browser automation
            const noteEl = document.getElementById('relocate-success-note');
            if (noteEl) {
                noteEl.textContent = data.note || 'Transfer will be processed automatically.';
                noteEl.classList.remove('hidden');
            }
        } else {
            document.getElementById('relocate-success-summary').textContent = 
                `${data.successCount || this.relocateSelectedItems.length} item(s) moved`;
            document.getElementById('relocate-success-from').textContent = `From: ${this.relocateSourceName}`;
            document.getElementById('relocate-success-to').textContent = `To: ${this.relocateDestName}`;
            document.getElementById('relocate-staff-name').textContent = data.movedBy || this.currentStaff?.displayName || 'Staff';
        }
        
        this.showScreen('relocate-success');
    },
    
    startNewRelocate() {
        this.relocateMultiSource = false;
        this.relocateSearchResults = null;
        this.relocateSearchPoId = null;
        this.relocateMode = 'location';
        
        // Reset search UI
        const searchInput = document.getElementById('relocate-search-input');
        if (searchInput) searchInput.value = '';
        const searchResults = document.getElementById('relocate-search-results');
        if (searchResults) searchResults.classList.add('hidden');
        const searchStatus = document.getElementById('relocate-search-status');
        if (searchStatus) searchStatus.classList.add('hidden');
        const moveBtn = document.getElementById('search-move-btn');
        if (moveBtn) moveBtn.style.display = 'none';
        
        // Reset mode toggle
        const locBtn = document.getElementById('relocate-mode-location');
        const srchBtn = document.getElementById('relocate-mode-search');
        if (locBtn) locBtn.classList.add('active');
        if (srchBtn) srchBtn.classList.remove('active');
        const locMode = document.getElementById('relocate-location-mode');
        const srchMode = document.getElementById('relocate-search-mode');
        if (locMode) locMode.classList.remove('hidden');
        if (srchMode) srchMode.classList.add('hidden');
        
        const loadBtn = document.getElementById('load-source-items-btn');
        if (loadBtn) loadBtn.style.display = '';
        
        this.relocateSourceId = null;
        this.relocateSourceName = null;
        this.relocateItems = [];
        this.relocateSelectedItems = [];
        this.relocateDestId = null;
        this.relocateDestName = null;
        
        document.getElementById('relocate-source-dropdown').value = '';
        document.getElementById('load-source-items-btn').disabled = true;
        document.getElementById('relocate-select-all').checked = false;
        document.getElementById('relocate-source-status').classList.add('hidden');
        
        this.showScreen('relocate-source');
    },
    
    // ============================================
    // Needs Receipting Dashboard
    // ============================================
    async loadReceiptingStatus() {
        try {
            const response = await this.authFetch('/api/needs-receipting');
            const data = await response.json();
            const alertEl = document.getElementById('receipting-alert');
            const iconEl = document.getElementById('receipting-icon');
            const textEl = document.getElementById('receipting-text');
            const detailsEl = document.getElementById('receipting-details');
            
            if (!alertEl) return;
            alertEl.style.display = 'block';
            
            if (data.count === 0) {
                iconEl.textContent = '🟢';
                textEl.textContent = 'All allocations receipted';
                detailsEl.style.display = 'none';
            } else {
                iconEl.textContent = '🔴';
                textEl.innerHTML = `<strong>${data.count}</strong> PO(s) allocated - check receipting status`;
                alertEl.onclick = () => {
                    detailsEl.style.display = detailsEl.style.display === 'none' ? 'block' : 'none';
                };
                alertEl.style.cursor = 'pointer';
                
                detailsEl.innerHTML = data.items.map(item => `
                    <div class="receipting-item">
                        <strong>PO #${item.po_number}</strong>
                        <span>${item.vendor_name || ''}</span>
                        <span>Job ${item.job_number || 'N/A'}</span>
                        <span>${item.total_items} item(s) → ${item.storage_location}</span>
                        <span class="receipting-date">${new Date(item.allocated_date).toLocaleDateString('en-AU')}</span>
                    </div>
                `).join('');
            }
        } catch (error) {
            console.error('Receipting status error:', error);
        }
    },

    // ============================================
    // Mystery Box Search
    // ============================================
    async searchMysteryBox() {
        const query = document.getElementById('mystery-search').value.trim();
        if (!query) return;
        
        const resultsEl = document.getElementById('mystery-results');
        resultsEl.innerHTML = '<p class="loading">🔍 Searching...</p>';
        
        try {
            const response = await fetch(`/api/search-mystery-box?q=${encodeURIComponent(query)}`);
            const data = await response.json();
            
            if (data.count === 0) {
                resultsEl.innerHTML = '<p class="no-results">❌ No matching records found</p>';
                return;
            }
            
            resultsEl.innerHTML = data.results.map(r => `
                <div class="mystery-result-card">
                    <div class="result-header">
                        <strong>PO #${r.po_number || 'N/A'}</strong>
                        <span class="result-date">${r.created_at ? new Date(r.created_at).toLocaleDateString('en-AU') : ''}</span>
                    </div>
                    <div class="result-details">
                        ${r.supplier_name ? `<div>📦 Supplier: ${r.supplier_name}</div>` : ''}
                        ${r.packing_slip_number ? `<div>📋 Packing Slip: ${r.packing_slip_number}</div>` : ''}
                        ${r.tracking_number ? `<div>🚚 Tracking #: ${r.tracking_number}</div>` : ''}
                        ${r.storage_location ? `<div>📍 Storage: ${r.storage_location}</div>` : ''}
                        ${r.receipt_job ? `<div>🔨 Job: ${r.receipt_job}</div>` : ''}
                        ${r.staff_name ? `<div>👤 Received by: ${r.staff_name}</div>` : ''}
                    </div>
                </div>
            `).join('');
        } catch (error) {
            resultsEl.innerHTML = `<p class="error">❌ Search failed: ${error.message}</p>`;
        }
    },

    // ============================================
    // Report Issue
    // ============================================
    _reportPhotos: [],
    
    // ============================================
    // Damaged Goods Reporting
    // ============================================
    showDamageModal(index) {
        this._damageItemIndex = index;
        this._damagePhotos = [];
        const item = this.currentPO.items[index];
        const po = this.currentPO;
        
        const modal = document.getElementById('damage-modal');
        modal.classList.remove('hidden');
        
        document.getElementById('damage-item-name').textContent = item.description;
        document.getElementById('damage-item-meta').textContent = 
            (item.partNo ? 'Part: ' + item.partNo + ' | ' : '') + 
            'PO #' + po.poNumber + ' | ' + (po.vendorName || 'Unknown vendor');
        
        const qtyInput = document.getElementById('damage-qty');
        qtyInput.value = item.quantityOrdered || 1;
        qtyInput.max = item.quantityOrdered || 99;
        
        document.getElementById('damage-notes').value = '';
        document.getElementById('damage-photo-preview').innerHTML = '';
        document.getElementById('damage-status').classList.add('hidden');
        document.getElementById('damage-submit-btn').disabled = false;
        document.getElementById('damage-submit-btn').innerHTML = '&#9888;&#65039; Report Damage';
    },
    
    hideDamageModal() {
        document.getElementById('damage-modal').classList.add('hidden');
        this._damagePhotos = [];
        this._damageItemIndex = null;
    },
    
    handleDamagePhotos(event) {
        const files = Array.from(event.target.files);
        const preview = document.getElementById('damage-photo-preview');
        
        files.forEach(async (file) => {
            if (this._damagePhotos.length >= 5) {
                alert('Maximum 5 photos per damage report');
                return;
            }
            
            let base64;
            try {
                base64 = await this.compressImage(file);
            } catch(e) {
                base64 = await new Promise(r => { const rd = new FileReader(); rd.onload = ev => r(ev.target.result); rd.readAsDataURL(file); });
            }
            this._damagePhotos.push(base64);
            
            const wrapper = document.createElement('div');
            wrapper.style.position = 'relative';
            wrapper.style.display = 'inline-block';
            
            const img = document.createElement('img');
            img.src = base64;
            wrapper.appendChild(img);
            
            const removeBtn = document.createElement('button');
            removeBtn.textContent = '\u2715';
            removeBtn.style.cssText = 'position:absolute;top:-6px;right:-6px;width:22px;height:22px;background:#ef4444;color:white;border:none;border-radius:50%;font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;';
            removeBtn.onclick = () => {
                const idx = this._damagePhotos.indexOf(base64);
                if (idx > -1) this._damagePhotos.splice(idx, 1);
                wrapper.remove();
            };
            wrapper.appendChild(removeBtn);
            
            preview.appendChild(wrapper);
        });
        
        event.target.value = '';
    },
    
    async submitDamageReport() {
        const statusEl = document.getElementById('damage-status');
        const submitBtn = document.getElementById('damage-submit-btn');
        const notes = document.getElementById('damage-notes').value.trim();
        const qty = parseInt(document.getElementById('damage-qty').value) || 1;
        
        if (this._damagePhotos.length === 0) {
            statusEl.textContent = 'Please take at least one photo of the damaged item';
            statusEl.className = 'status-message error';
            statusEl.classList.remove('hidden');
            return;
        }
        
        submitBtn.disabled = true;
        submitBtn.textContent = '\u23f3 Submitting...';
        statusEl.textContent = 'Reporting damage...';
        statusEl.className = 'status-message info';
        statusEl.classList.remove('hidden');
        
        const item = this.currentPO.items[this._damageItemIndex];
        const po = this.currentPO;
        
        const payload = {
            po_number: po.poNumber,
            po_id: po.ID,
            catalog_id: item.catalogId,
            item_description: item.description,
            part_number: item.partNo || '',
            quantity_damaged: qty,
            notes: notes,
            photos: this._damagePhotos,
            vendor_name: po.vendorName || '',
            vendor_id: po.vendorID || '',
            job_number: po.jobNumber || item.jobNumber || '',
            customer_name: po.customerName || item.customerName || ''
        };
        
        try {
            const resp = await this.authFetch('/api/report-damage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const data = await resp.json();
            
            if (data.success) {
                statusEl.innerHTML = '\u2705 ' + data.message + ' (Ref: ' + data.report_id + ')';
                statusEl.className = 'status-message success';
                statusEl.classList.remove('hidden');
                
                const card = document.querySelector('.item-card[data-index="' + this._damageItemIndex + '"]');
                if (card) {
                    card.classList.add('damaged');
                    const dmgBadge = document.createElement('div');
                    dmgBadge.className = 'damage-badge';
                    dmgBadge.innerHTML = '\u26a0\ufe0f DAMAGED \u2014 Reported';
                    const details = card.querySelector('.item-details');
                    if (details) details.appendChild(dmgBadge);
                }
                
                setTimeout(() => {
                    this.hideDamageModal();
                }, 2000);
            } else {
                throw new Error(data.error || 'Failed to submit');
            }
        } catch (err) {
            statusEl.textContent = '\u274c Failed: ' + err.message;
            statusEl.className = 'status-message error';
            statusEl.classList.remove('hidden');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '&#9888;&#65039; Report Damage';
        }
    },
    

    showReportIssue() {
        const modal = document.getElementById('report-issue-modal');
        modal.classList.remove('hidden');
        
        // Auto-populate name from logged-in user
        const nameInput = document.getElementById('report-name');
        if (this.currentStaff?.displayName) {
            nameInput.value = this.currentStaff.displayName;
            nameInput.readOnly = true;
        } else {
            const staffName = document.getElementById('staff-name')?.textContent;
            if (staffName && staffName !== 'Staff') {
                nameInput.value = staffName;
                nameInput.readOnly = true;
            }
        }
        
        // Auto-populate email from logged-in user
        const emailField = document.getElementById('report-email');
        if (emailField) {
            if (this.currentStaff?.email) {
                emailField.value = this.currentStaff.email;
                emailField.readOnly = true;
            } else {
                emailField.value = '';
                emailField.readOnly = false;
                emailField.placeholder = 'No email on file - enter your email';
            }
        }
        
        // Auto-capture context
        this._captureContext();
        
        // Set up photo handlers for camera and library inputs
        const cameraInput = document.getElementById('report-photos-camera');
        if (cameraInput) cameraInput.onchange = (e) => this._handleReportPhotos(e);
        const libraryInput = document.getElementById('report-photos-library');
        if (libraryInput) libraryInput.onchange = (e) => this._handleReportPhotos(e);
        
        // Reset
        this._reportPhotos = [];
        document.getElementById('report-photo-preview').innerHTML = '';
        document.getElementById('report-status').classList.add('hidden');
        document.getElementById('report-submit-btn').disabled = false;
    },
    
    hideReportIssue() {
        document.getElementById('report-issue-modal').classList.add('hidden');
    },
    
    _captureContext() {
        const ctx = document.getElementById('report-context');
        const parts = [];
        
        // Current screen
        const activeScreen = document.querySelector('.screen.active');
        if (activeScreen) {
            parts.push(`<p><strong>Screen:</strong> ${activeScreen.id}</p>`);
        }
        
        // Current PO if any
        if (this.currentPO) {
            parts.push(`<p><strong>PO:</strong> ${this.currentPO.ID || 'N/A'}</p>`);
        }
        if (this.currentJobNumber) {
            parts.push(`<p><strong>Job:</strong> ${this.currentJobNumber}</p>`);
        }
        
        // Any visible error messages
        const errors = document.querySelectorAll('.status-message.error:not(.hidden)');
        errors.forEach(el => {
            if (el.textContent) parts.push(`<p><strong>Error:</strong> ${el.textContent}</p>`);
        });
        
        ctx.innerHTML = parts.length > 0 
            ? '<p style="margin-bottom:4px;"><strong>📋 Auto-captured info:</strong></p>' + parts.join('')
            : '<p>No additional context detected</p>';
    },
    
    _handleReportPhotos(event) {
        const files = Array.from(event.target.files);
        const preview = document.getElementById('report-photo-preview');
        
        files.forEach(async (file) => {
            let base64;
            try {
                base64 = await this.compressImage(file);
            } catch(e) {
                base64 = await new Promise(r => { const rd = new FileReader(); rd.onload = ev => r(ev.target.result); rd.readAsDataURL(file); });
            }
                this._reportPhotos.push(base64);
                
                const wrapper = document.createElement('div');
                wrapper.style.position = 'relative';
                wrapper.style.display = 'inline-block';
                
                const img = document.createElement('img');
                img.src = base64;
                wrapper.appendChild(img);
                
                const removeBtn = document.createElement('button');
                removeBtn.textContent = '✕';
                removeBtn.style.cssText = 'position:absolute;top:-6px;right:-6px;width:22px;height:22px;background:#ef4444;color:white;border:none;border-radius:50%;font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;';
                removeBtn.onclick = () => {
                    const idx = this._reportPhotos.indexOf(base64);
                    if (idx > -1) this._reportPhotos.splice(idx, 1);
                    wrapper.remove();
                };
                wrapper.appendChild(removeBtn);
                
                preview.appendChild(wrapper);
        });
    },
    
    async submitFaultReport() {
        const name = document.getElementById('report-name').value.trim();
        const email = document.getElementById('report-email').value.trim();
        const description = document.getElementById('report-description').value.trim();
        const statusEl = document.getElementById('report-status');
        const submitBtn = document.getElementById('report-submit-btn');
        
        // Validate
        if (!name || !email || !description) {
            statusEl.textContent = 'Please fill in all required fields (*)';
            statusEl.className = 'status-message error';
            statusEl.classList.remove('hidden');
            return;
        }
        
        if (!email.includes('@')) {
            statusEl.textContent = 'Please enter a valid email address';
            statusEl.className = 'status-message error';
            statusEl.classList.remove('hidden');
            return;
        }
        
        // Disable submit
        submitBtn.disabled = true;
        submitBtn.textContent = '⏳ Submitting...';
        statusEl.textContent = 'Sending your report...';
        statusEl.className = 'status-message info';
        statusEl.classList.remove('hidden');
        
        // Build payload
        const activeScreen = document.querySelector('.screen.active');
        const errors = [];
        document.querySelectorAll('.status-message.error:not(.hidden)').forEach(el => {
            if (el.textContent && el.id !== 'report-status') errors.push(el.textContent);
        });
        
        const payload = {
            reporter_name: name,
            reporter_email: email,
            description: description,
            po_number: this.currentPO?.ID || '',
            job_number: this.currentJobNumber || '',
            current_screen: activeScreen?.id || '',
            error_message: errors.join(' | '),
            photos: this._reportPhotos
        };
        
        try {
            const resp = await this.authFetch('/api/report-fault', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const data = await resp.json();
            
            if (data.success) {
                statusEl.textContent = `✅ ${data.message} (Ref: ${data.report_id})`;
                statusEl.className = 'status-message success';
                statusEl.classList.remove('hidden');
                
                // Clear form after 2s
                setTimeout(() => {
                    document.getElementById('report-description').value = '';
                    document.getElementById('report-photo-preview').innerHTML = '';
                    this._reportPhotos = [];
                    this.hideReportIssue();
                }, 3000);
            } else {
                throw new Error(data.error || 'Failed to submit');
            }
        } catch (err) {
            statusEl.textContent = `❌ Failed: ${err.message}`;
            statusEl.className = 'status-message error';
            statusEl.classList.remove('hidden');
            submitBtn.disabled = false;
            submitBtn.textContent = '📤 Submit Report';
        }
    },
    
    // ============================================
    // Utilities
    // ============================================

    showAwaitingAllocModal(itemJson) {
        let item;
        try {
            // itemJson is base64 encoded to avoid quote issues in onclick attributes
            const decoded = decodeURIComponent(escape(atob(itemJson)));
            item = JSON.parse(decoded);
        } catch(e) { alert('Error parsing item: ' + e.message); return; }
        
        // Remove existing modal if any
        document.getElementById('awaiting-modal')?.remove();
        
        const modal = document.createElement('div');
        modal.id = 'awaiting-modal';
        modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:9999;overflow-y:auto;padding:16px;';
        
        modal.innerHTML = `
            <div style="background:#1e293b;border-radius:12px;padding:16px;max-width:480px;margin:0 auto;margin-top:20px;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
                    <div>
                        <div style="font-weight:700;color:#e2e8f0;font-size:15px;">${item.description || 'Unknown Item'}</div>
                        <div style="font-size:12px;color:#64748b;margin-top:2px;">${item.partNo || ''} · Job ${item.jobNumber || ''}</div>
                    </div>
                    <button onclick="document.getElementById('awaiting-modal').remove()" style="background:#334155;border:none;color:#94a3b8;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:14px;">✕</button>
                </div>
                
                <div id="aw-modal-body">
                    <p style="color:#94a3b8;font-size:13px;">🔍 Searching for stock...</p>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Fetch stock locations and storage list in parallel
        Promise.all([
            this.authFetch('/api/stock-part-search', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ partNumber: item.partNo })
            }).then(r => r.json()),
            this.authFetch('/api/storage-locations').then(r => r.json())
        ]).then(([stockData, storageData]) => {
            const body = document.getElementById('aw-modal-body');
            if (!body) return;
            
            const locations = stockData.items || [];
            const storages = Array.isArray(storageData) ? storageData : (storageData.locations || []);
            
            if (locations.length === 0) {
                body.innerHTML = `<p style="color:#f59e0b;font-size:13px;">⚠️ No stock found for part number <strong>${item.partNo}</strong>.<br><br>Item may not be in any storage location yet. Use PO receiving to receipt the goods first.</p>`;
                return;
            }
            
            // Build source location picker
            let html = '<div style="font-size:12px;color:#94a3b8;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">📦 Available Stock</div>';
            html += '<div id="aw-locations">';
            locations.forEach((loc, idx) => {
                html += `<div id="aw-loc-${idx}" onclick="app._selectAwaitingSource(${idx})" style="cursor:pointer;border:2px solid #334155;border-radius:8px;padding:10px 12px;margin-bottom:8px;background:#0f172a;transition:border-color 0.15s;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <div style="color:#e2e8f0;font-weight:600;font-size:13px;">${loc.storageName}</div>
                            <div style="color:#64748b;font-size:12px;">${loc.partNo}</div>
                        </div>
                        <div style="color:#22d3ee;font-weight:700;font-size:15px;">× ${loc.quantity}</div>
                    </div>
                </div>`;
            });
            html += '</div>';
            
            // Quantity input
            const defaultQty = item.quantity > 0 ? item.quantity : 1;
            html += `<div style="margin-top:12px;">
                <label style="font-size:12px;color:#94a3b8;font-weight:600;display:block;margin-bottom:4px;">QUANTITY</label>
                <input id="aw-qty" type="number" min="1" value="${defaultQty}" style="width:100%;padding:8px 10px;border-radius:6px;background:#0f172a;border:1px solid #334155;color:#e2e8f0;font-size:14px;box-sizing:border-box;">
            </div>`;
            
            // Destination storage dropdown
            html += `<div style="margin-top:12px;">
                <label style="font-size:12px;color:#94a3b8;font-weight:600;display:block;margin-bottom:4px;">PUT IN STORAGE</label>
                <select id="aw-dest" style="width:100%;padding:8px 10px;border-radius:6px;background:#0f172a;border:1px solid #334155;color:#e2e8f0;font-size:14px;box-sizing:border-box;">
                    <option value="">Select storage location...</option>`;
            storages.forEach(s => {
                html += `<option value="${s.ID || s.id}">${s.Name || s.name}</option>`;
            });
            html += `</select></div>`;
            
            // CC confirm area
            html += `<div id="aw-cc-area"></div>`;
            
            // Check CC button
            html += `<button id="aw-check-cc-btn" onclick="app._awCheckCC()" style="width:100%;margin-top:14px;padding:12px;border-radius:8px;background:#2563eb;color:#fff;font-weight:700;border:none;cursor:pointer;font-size:14px;">Check Cost Centre & Continue →</button>`;
            
            body.innerHTML = html;
            
            // Store locations and item for later
            this._awLocations = locations;
            this._awItem = item;
            this._awSelectedLocIdx = null;
            
        }).catch(err => {
            const body = document.getElementById('aw-modal-body');
            if (body) body.innerHTML = `<p style="color:#ef4444;">Error: ${err.message}</p>`;
        });
    },

    _selectAwaitingSource(idx) {
        // Clear all selections
        const locs = this._awLocations || [];
        locs.forEach((_, i) => {
            const el = document.getElementById('aw-loc-' + i);
            if (el) el.style.borderColor = '#334155';
        });
        // Highlight selected
        const sel = document.getElementById('aw-loc-' + idx);
        if (sel) sel.style.borderColor = '#22d3ee';
        this._awSelectedLocIdx = idx;
    },

    async _awCheckCC() {
        const item = this._awItem;
        if (!item) return;
        
        const locIdx = this._awSelectedLocIdx;
        if (locIdx === null || locIdx === undefined) {
            alert('Please select a source storage location first.');
            return;
        }
        
        const sourceLoc = this._awLocations[locIdx];
        const destDropdown = document.getElementById('aw-dest');
        const destId = destDropdown?.value;
        const destName = destDropdown?.options[destDropdown.selectedIndex]?.text || '';
        
        if (!destId) {
            alert('Please select a destination storage location.');
            return;
        }
        
        const qty = parseInt(document.getElementById('aw-qty')?.value) || 1;
        const btn = document.getElementById('aw-check-cc-btn');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Checking cost centre...'; }
        
        try {
            const resp = await this.authFetch('/api/job-cc-lookup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    jobId: parseInt(item.jobId),
                    catalogId: item.catalogId,
                    partNo: item.partNo,
                    description: item.description
                })
            });
            const data = await resp.json();
            
            if (btn) { btn.disabled = false; btn.textContent = 'Check Cost Centre & Continue →'; }
            
            const ccArea = document.getElementById('aw-cc-area');
            if (!ccArea) return;
            
            if (data.error || !data.matches || data.matches.length === 0) {
                // Item not on job — show warning
                ccArea.innerHTML = `<div style="margin-top:12px;border:2px solid #f59e0b;border-radius:8px;padding:12px;background:#0f172a;">
                    <div style="color:#f59e0b;font-weight:600;margin-bottom:8px;">⚠️ Item Not Found on Job</div>
                    <div style="color:#94a3b8;font-size:13px;">This item is not on Job ${item.jobNumber}'s material list. It cannot be allocated automatically.<br><br>Use the stock screen to manually allocate it.</div>
                </div>`;
                return;
            }
            
            // Store for allocation
            this._awSourceLoc = sourceLoc;
            this._awDestId = destId;
            this._awDestName = destName;
            this._awQty = qty;
            this._awMatches = data.matches;
            this._awJobInfo = data.job || {};
            
            // Show CC choices
            let html = '<div style="margin-top:12px;border:2px solid #22d3ee;border-radius:8px;padding:12px;background:#0f172a;">';
            html += '<div style="color:#22d3ee;font-weight:600;margin-bottom:10px;">✅ Select Cost Centre</div>';
            data.matches.forEach((m, i) => {
                const remaining = (m.required || 0) - (m.allocated || 0);
                html += `<label style="display:flex;align-items:flex-start;gap:10px;margin-bottom:8px;cursor:pointer;">
                    <input type="radio" name="aw-cc" value="${i}" ${i === 0 ? 'checked' : ''} style="margin-top:2px;flex-shrink:0;">
                    <div>
                        <div style="color:#e2e8f0;font-weight:600;font-size:13px;">${m.costCentreName || 'Cost Centre ' + m.costCentreId}</div>
                        <div style="color:#64748b;font-size:12px;">Required: ${m.required || 0} · Allocated: ${m.allocated || 0} · Remaining: ${remaining}</div>
                    </div>
                </label>`;
            });
            html += `<button onclick="app._awConfirmAlloc()" style="width:100%;margin-top:10px;padding:12px;border-radius:8px;background:#16a34a;color:#fff;font-weight:700;border:none;cursor:pointer;font-size:14px;" id="aw-confirm-btn">✅ Allocate + Print Labels</button>`;
            html += '</div>';
            ccArea.innerHTML = html;
            
        } catch(err) {
            if (btn) { btn.disabled = false; btn.textContent = 'Check Cost Centre & Continue →'; }
            alert('CC lookup error: ' + err.message);
        }
    },

    async _awConfirmAlloc() {
        const item = this._awItem;
        const sourceLoc = this._awSourceLoc;
        const matches = this._awMatches || [];
        const jobInfo = this._awJobInfo || {};
        
        const selected = document.querySelector('input[name="aw-cc"]:checked');
        const matchIdx = selected ? parseInt(selected.value) : 0;
        const match = matches[matchIdx];
        
        if (!match) { alert('Please select a cost centre.'); return; }
        
        const btn = document.getElementById('aw-confirm-btn');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Allocating...'; }
        
        const qty = this._awQty || 1;
        const destId = this._awDestId;
        const destName = this._awDestName;
        
        const payload = {
            destId: parseInt(destId),
            destName: destName,
            jobNumber: item.jobNumber,
            customerName: jobInfo.customerName || jobInfo.customer || '',
            targetJobId: parseInt(item.jobId),
            items: [{
                catalogId: item.catalogId,
                partNo: item.partNo,
                description: item.description,
                quantity: qty,
                sourceId: sourceLoc.storageId,
                sourceName: sourceLoc.storageName,
                jobId: parseInt(item.jobId),
                sectionId: match.sectionId,
                costCentreId: match.costCentreId
            }]
        };
        
        try {
            const resp = await this.authFetch('/api/allocate-from-stock', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const result = await resp.json();
            
            if (result.error) {
                if (btn) { btn.disabled = false; btn.textContent = '✅ Allocate + Print Labels'; }
                alert('Error: ' + result.error);
                return;
            }
            
            const customerName = result.customerName || jobInfo.customerName || jobInfo.customer || '';
            const jobNumber = result.jobNumber || item.jobNumber;
            const successCount = result.results ? result.results.filter(r => r.success).length : 0;
            const failCount = result.results ? result.results.filter(r => !r.success).length : 0;
            
            // Generate labels
            if (successCount > 0) {
                const labelItems = [{
                    jobNumber: jobNumber,
                    customerName: customerName,
                    partNo: item.partNo,
                    description: item.description,
                    quantity: qty,
                    storageLocation: destName
                }];
                await this.generateAndShowLabels(labelItems, item.poOrderNo || 'Stock');
            }
            
            // Close modal
            document.getElementById('awaiting-modal')?.remove();
            
            // Show result
            let msg = successCount > 0 ? '✅ ' + successCount + ' item(s) allocated to ' + destName : '';
            if (failCount > 0) {
                msg += (msg ? '\n' : '') + '⚠️ ' + failCount + ' failed: ';
                result.results.filter(r => !r.success).forEach(r => { msg += '\n  - ' + (r.error || 'Unknown'); });
            }
            if (msg) alert(msg);
            
            // Refresh job view on stock screen if it's showing the same job
            const jobNumEl = document.getElementById('job-number');
            if (jobNumEl && jobNumEl.value === item.jobNumber) {
                this.stockJobLookup();
            }
            
        } catch(err) {
            if (btn) { btn.disabled = false; btn.textContent = '✅ Allocate + Print Labels'; }
            alert('Allocation error: ' + err.message);
        }
    },
    showStatus(elementId, message, type) {
        const el = document.getElementById(elementId);
        if (el) {
            el.textContent = message;
            el.className = `status-message ${type}`;
            el.classList.remove('hidden');
        }
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => app.init());

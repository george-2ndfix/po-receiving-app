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
    photoMode: null, // 'individual', 'group', or 'skip'
    individualPhotos: [], // [{itemIndex, description, base64}]
    
    // Relocate state
    relocateJobId: null,
    relocateJobNumber: null,
    relocateCustomer: null,
    relocateItems: [],
    relocateSelectedItems: [],
    relocateDestId: null,
    relocateDestName: null,
    relocateLabelItems: [],
    
    // ============================================
    // Initialization
    // ============================================
    init() {
        this.bindEvents();
        this.checkAuthStatus();
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
        document.getElementById('option-picklist')?.addEventListener('click', () => this.showPicklist());
        document.getElementById('option-relocate')?.addEventListener('click', () => this.showScreen('relocate-source'));
        document.getElementById('option-mystery')?.addEventListener('click', () => this.showScreen('mystery'));
        document.getElementById('option-collection')?.addEventListener('click', () => this.showScreen('collection'));
        document.getElementById('mystery-search')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.searchMysteryBox();
        });
        document.getElementById('option-labels')?.addEventListener('click', () => this.showScreen('labels'));
        document.getElementById('option-sop')?.addEventListener('click', () => this.showScreen('sop'));
        document.getElementById('option-test-print')?.addEventListener('click', () => this.testPrint());
        document.getElementById('label-po-input')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.lookupLabels();
        });
        document.getElementById('label-lookup-btn')?.addEventListener('click', () => this.lookupLabels());
        
        // Relocate flow
        document.getElementById('relocate-job-lookup-btn')?.addEventListener('click', () => this.relocateLookupJob());
        document.getElementById('relocate-job-number')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') this.relocateLookupJob(); });
        document.getElementById('to-relocate-dest-btn')?.addEventListener('click', () => this.showRelocateDestScreen());
        document.getElementById('relocate-dest-dropdown')?.addEventListener('change', (e) => this.selectRelocateDest(e));
        document.getElementById('execute-relocate-btn')?.addEventListener('click', () => this.executeRelocate());
        document.getElementById('relocate-print-labels-btn')?.addEventListener('click', () => this.relocatePrintLabels());
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
        document.getElementById('to-storage-btn')?.addEventListener('click', () => this.showScreen('storage'));
        
        // Storage selection
        document.getElementById('storage-dropdown')?.addEventListener('change', (e) => this.selectStorage(e));
        document.getElementById('allocate-btn')?.addEventListener('click', () => this.allocateItems());
        
        // Success screen
        document.getElementById('new-po-btn')?.addEventListener('click', () => this.startNewPO());
document.getElementById('view-history-btn')?.addEventListener('click', () => this.showLogs());
        document.getElementById('print-labels-btn')?.addEventListener('click', () => this.printLabels());
        
        // Allocate from Stock - Look Up
        document.getElementById('job-lookup-btn')?.addEventListener('click', () => this.stockLookup());
        document.getElementById('job-number')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.stockLookup();
        });
        document.getElementById('part-search-btn')?.addEventListener('click', () => this.partSearch());
        
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
        try {
            const response = await fetch('/api/auth/status');
            const data = await response.json();
            
            if (data.authenticated) {
                this.currentStaff = data.staff;
                this.showHomeScreen();
            } else {
                this.showScreen('login');
            }
        } catch (error) {
            console.error('Auth check failed:', error);
            this.showScreen('login');
        }
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
            const response = await fetch('/api/staff');
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
                response = await fetch('/api/staff', {
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
            const response = await fetch('/api/logs?limit=50');
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
        
        itemsList.innerHTML = this.currentPO.items.map((item, index) => {
            const statusClass = item.receiptStatus === 'fully_receipted' ? 'receipted' 
                : item.receiptStatus === 'partially_receipted' ? 'partial' : 'pending';
            const statusText = item.receiptStatus === 'fully_receipted' ? 'Fully receipted'
                : item.receiptStatus === 'partially_receipted' ? 'Partially receipted' : 'Not yet receipted';
            const remaining = item.quantityOrdered - item.quantityReceived;
            
            return `
                <div class="item-card ${statusClass}" data-index="${index}" data-catalog-id="${item.catalogId}">
                    <label class="item-checkbox">
                        <input type="checkbox" onchange="app.toggleItem(${index})">
                        <span class="checkmark"></span>
                    </label>
                    <div class="item-details">
                        <div class="item-name">${item.description}</div>
                        <div class="item-meta">
                            ${item.partNo ? `<span class="item-part">${item.partNo}</span>` : ''}
                            ${item.jobNumber ? `<span class="item-job">Job ${item.jobNumber}${item.customerName ? ' - ' + item.customerName : ''}</span>` : ''}
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
                customerName: item.customerName
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
                    customerName: item.customerName
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
            const response = await fetch('/api/allocate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
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
                        quantityReceived: item.quantityReceived || 0
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
                        await fetch('/api/backorder', {
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
                        await fetch('/api/docket-data', {
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
                                filename: `PO_${this.currentPO.poNumber}_delivery_${dateStr}.jpg`
                            });
                        } else if (this.photoMode === 'individual') {
                            this.individualPhotos.forEach(p => {
                                const safeName = (p.partNo || p.description || 'item').replace(/[^a-zA-Z0-9]/g, '_').substring(0, 30);
                                photos.push({
                                    base64: p.base64,
                                    filename: `PO_${this.currentPO.poNumber}_${safeName}_${dateStr}.jpg`
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
                                const uploadResp = await fetch('/api/upload-photos', {
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
                const errMsg = data.error || 'Unknown error';
                const failedItems = (data.results || []).filter(r => !r.success);
                let detail = `Allocation failed for PO ${this.currentPO.poNumber}: ${errMsg}`;
                if (failedItems.length > 0) {
                    detail += '\n\nFailed items:\n' + failedItems.map(f => 
                        `• ${f.catalogId}: ${f.error || 'Unknown'}${f.detail ? ' - ' + f.detail.substring(0, 100) : ''}`
                    ).join('\n');
                }
                alert(detail);
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
        document.getElementById('label-count').textContent = `${totalLabels} labels ready to print`;
        
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
            
            const response = await fetch('/api/picking-slip/generate', {
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
            const response = await fetch('/api/stock-pick-list');
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
            const response = await fetch('/api/stock-pick-list');
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
        
        // Store docket photo as base64
        const reader = new FileReader();
        reader.onload = (e) => { this.docketPhoto = e.target.result; };
        reader.readAsDataURL(file);
        
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
                            <input type="file" accept="image/*" capture="environment" id="photo-input-${index}" hidden
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

    handleIndividualPhoto(index, event) {
        const file = event.target.files[0];
        if (!file) return;
        
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target.result;
            
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
        };
        reader.readAsDataURL(file);
    },

    removeIndividualPhoto(index) {
        this.individualPhotos = this.individualPhotos.filter(p => p.itemIndex !== index);
        document.getElementById(`photo-preview-${index}`).classList.add('hidden');
        document.getElementById(`photo-capture-${index}`).classList.remove('hidden');
        document.getElementById(`photo-input-${index}`).value = '';
    },

    handleEvidencePhoto(event) {
        const file = event.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                this.evidencePhoto = e.target.result;
                document.getElementById('evidence-img').src = e.target.result;
                document.getElementById('evidence-preview').classList.remove('hidden');
                document.getElementById('evidence-capture').classList.add('hidden');
            };
            reader.readAsDataURL(file);
        }
    },
    
    removeEvidencePhoto() {
        this.evidencePhoto = null;
        document.getElementById('evidence-preview').classList.add('hidden');
        document.getElementById('evidence-capture').classList.remove('hidden');
        document.getElementById('evidence-photo').value = '';
    },
    
    // ============================================
    // Labels
    // ============================================
    async testPrint() {
        const isAndroid = /Android/i.test(navigator.userAgent);
        const device = isAndroid ? 'Android' : 'iPhone/Desktop';
        const testItems = [{
            jobNumber: '9999',
            customerName: 'TEST CUSTOMER',
            partNo: 'TEST-001',
            description: 'Test Label — ' + device,
            quantity: 1,
            storageLocation: 'Test Storage'
        }];
        await this.generateAndShowLabels(testItems, 'TEST');
    },

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
        const today = new Date().toLocaleDateString('en-AU', { day: '2-digit', month: '2-digit', year: 'numeric' });
        const isAndroid = /Android/i.test(navigator.userAgent);
        
        // Build label data (shared between PDF and HTML paths)
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
            
            for (let i = 0; i < qty; i++) {
                labels.push({ line1, line2, line3 });
            }
        }
        
        // Add filing label at the end (for job orders only)
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
        
        // All devices: Server-side PDF (v95 gold standard)
        if (isAndroid) {
            this._showAndroidLabels(labels, items, poNumber);
        } else {
            this._showPdfLabels(labels, items, poNumber);
        }
    },

    _showAndroidLabels(labels, items, poNumber) {
        let labelsHtml = '';
        for (const label of labels) {
            const isFiling = label.type === 'filing';
            labelsHtml += `
                <div style="page-break-after:always;width:100%;max-width:300px;height:80px;box-sizing:border-box;padding:4px 8px;display:flex;flex-direction:column;justify-content:center;font-family:Helvetica,Arial,sans-serif;overflow:hidden;border:1px solid #ddd;margin-bottom:4px;border-radius:4px;">
                    <div style="font-size:${isFiling ? '10pt' : '14pt'};font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${label.line1}</div>
                    <div style="font-size:${isFiling ? '9pt' : '12pt'};font-weight:bold;margin-top:1mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${label.line2}</div>
                    <div style="font-size:${isFiling ? '8pt' : '10pt'};margin-top:1mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${label.line3}</div>
                </div>
            `;
        }
        
        var overlay = document.getElementById('label-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'label-overlay';
            overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:10000;display:flex;flex-direction:column;align-items:center;padding:10px;overflow-y:auto;';
            document.body.appendChild(overlay);
        }
        overlay.style.display = 'flex';
        overlay.innerHTML = `
            <div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;justify-content:center;">
                <button id="android-print-btn" style="padding:12px 24px;background:#059669;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">\ud83d\udda8\ufe0f Print Labels</button>
                <button id="print-later-btn" style="padding:12px 24px;background:#f59e0b;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">\ud83d\udce5 Print Later</button>
                <button onclick="document.getElementById('label-overlay').style.display='none'" style="padding:12px 24px;background:#dc2626;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">\u2716 Close</button>
            </div>
            <div id="android-label-preview" style="background:white;border-radius:8px;padding:10px;max-width:600px;width:100%;overflow-y:auto;flex:1;">
                ${labelsHtml}
            </div>
        `;
        
        // Wire Print button - opens Chrome print dialog with @page CSS
        document.getElementById('android-print-btn').onclick = () => {
            const printWindow = window.open('', '_blank');
            printWindow.document.write(`
                <html><head><style>
                    @page { size: 120mm 38mm; margin: 0; }
                    body { margin: 0; padding: 0; }
                    .label { width:120mm; height:38mm; box-sizing:border-box; padding:2mm 3mm; display:flex; flex-direction:column; justify-content:center; font-family:Helvetica,Arial,sans-serif; overflow:hidden; page-break-after:always; }
                    .l1 { font-size:14pt; font-weight:bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
                    .l2 { font-size:12pt; font-weight:bold; margin-top:1mm; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
                    .l3 { font-size:10pt; margin-top:1mm; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
                    .filing .l1 { font-size:10pt; } .filing .l2 { font-size:9pt; } .filing .l3 { font-size:8pt; }
                </style></head><body>
            `);
            for (const label of labels) {
                const cls = label.type === 'filing' ? 'label filing' : 'label';
                printWindow.document.write(`<div class="${cls}"><div class="l1">${label.line1}</div><div class="l2">${label.line2}</div><div class="l3">${label.line3}</div></div>`);
            }
            printWindow.document.write('</body></html>');
            printWindow.document.close();
            printWindow.print();
        };
        
        // Wire Print Later
        const printLaterBtn = document.getElementById('print-later-btn');
        if (printLaterBtn) {
            printLaterBtn.onclick = () => {
                const desc = items.length > 0 ? ('Job ' + (items[0].jobNumber || 'N/A') + ' - PO ' + poNumber) : 'Labels';
                this.saveLabelsToPrintQueue(labels, desc);
                document.getElementById('label-overlay').style.display = 'none';
            };
        }
    },

    async _showPdfLabels(labels, items, poNumber) {
        try {
            const response = await fetch('/api/label-pdf', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${this.token}` },
                body: JSON.stringify({ labels })
            });
            
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || 'Failed to generate labels');
            }
            
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            
            var overlay = document.getElementById('label-overlay');
            if (!overlay) {
                overlay = document.createElement('div');
                overlay.id = 'label-overlay';
                overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:10000;display:flex;flex-direction:column;align-items:center;padding:10px;';
                document.body.appendChild(overlay);
            }
            overlay.style.display = 'flex';
            overlay.innerHTML = `
                <div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;justify-content:center;">
                    <a href="${url}" download="labels.pdf" style="padding:12px 24px;background:#2563eb;color:white;border-radius:8px;text-decoration:none;font-size:16px;font-weight:600;">\u2b07\ufe0f Download PDF</a>
                    <button onclick="window.open('${url}','_blank')" style="padding:12px 24px;background:#059669;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">\ud83d\udda8\ufe0f Open to Print</button>
                    <button id="print-later-btn" style="padding:12px 24px;background:#f59e0b;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">\ud83d\udce5 Print Later</button>
                    <button onclick="document.getElementById('label-overlay').style.display='none'" style="padding:12px 24px;background:#dc2626;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">\u2716 Close</button>
                </div>
                <iframe src="${url}" style="flex:1;width:100%;max-width:600px;border:none;border-radius:8px;background:white;"></iframe>
            `;
            
            const printLaterBtn = document.getElementById('print-later-btn');
            if (printLaterBtn) {
                printLaterBtn.onclick = () => {
                    const desc = items.length > 0 ? ('Job ' + (items[0].jobNumber || 'N/A') + ' - PO ' + poNumber) : 'Labels';
                    this.saveLabelsToPrintQueue(labels, desc);
                    document.getElementById('label-overlay').style.display = 'none';
                };
            }

            setTimeout(() => URL.revokeObjectURL(url), 300000);
            
        } catch (err) {
            console.error('Label PDF error:', err);
            const desc = items.length > 0 ? ('Job ' + (items[0].jobNumber || 'N/A') + ' - PO ' + poNumber) : 'Labels';
            this.saveLabelsToPrintQueue(labels, desc);
        }
    },

    // ============================================
    // Print Later Queue
    // ============================================
    saveLabelsToPrintQueue(labels, description) {
        const queue = JSON.parse(localStorage.getItem('label_print_queue') || '[]');
        queue.push({
            labels: labels,
            description: description || 'Labels',
            savedAt: new Date().toISOString(),
            id: Date.now().toString(36)
        });
        localStorage.setItem('label_print_queue', JSON.stringify(queue));
        this.updatePrintQueueBadge();
        alert('\u2705 Labels saved to print queue. Tap the printer icon when you\'re back on WiFi.');
    },

    getPrintQueue() {
        return JSON.parse(localStorage.getItem('label_print_queue') || '[]');
    },

    updatePrintQueueBadge() {
        const queue = this.getPrintQueue();
        let badge = document.getElementById('print-queue-badge');
        if (!badge) {
            badge = document.createElement('button');
            badge.id = 'print-queue-badge';
            badge.onclick = () => this.showPrintQueue();
            document.body.appendChild(badge);
        }
        if (queue.length > 0) {
            badge.style.display = 'flex';
            badge.innerHTML = '\ud83d\udda8\ufe0f ' + queue.length;
        } else {
            badge.style.display = 'none';
        }
    },

    async showPrintQueue() {
        const queue = this.getPrintQueue();
        if (queue.length === 0) {
            alert('Print queue is empty.');
            return;
        }

        const allLabels = [];
        const descriptions = [];
        for (const item of queue) {
            allLabels.push(...item.labels);
            descriptions.push(item.description);
        }

        try {
            const response = await fetch('/api/label-pdf', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ labels: allLabels })
            });

            if (!response.ok) {
                throw new Error('Still offline or server error. Try again when connected to WiFi.');
            }

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);

            var overlay = document.getElementById('label-overlay');
            if (!overlay) {
                overlay = document.createElement('div');
                overlay.id = 'label-overlay';
                overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:10000;display:flex;flex-direction:column;align-items:center;padding:10px;';
                document.body.appendChild(overlay);
            }
            overlay.style.display = 'flex';
            overlay.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center;width:100%;max-width:600px;margin-bottom:8px;">
                    <div style="color:white;font-size:14px;text-align:center;flex:1;">
                        \ud83d\udda8\ufe0f Print Queue: ${allLabels.length} label(s) from ${queue.length} job(s)
                    </div>
                    <button id="close-queue-btn" style="background:none;border:none;color:white;font-size:28px;cursor:pointer;padding:4px 8px;">\u2716</button>
                </div>
                <div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;justify-content:center;">
                    <a href="${url}" download="print_queue_labels.pdf" style="padding:12px 24px;background:#2563eb;color:white;border-radius:8px;text-decoration:none;font-size:16px;font-weight:600;">\u2b07\ufe0f Download PDF</a>
                    <button onclick="window.open('${url}','_blank')" style="padding:12px 24px;background:#059669;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">\ud83d\udda8\ufe0f Open to Print</button>
                    <button id="clear-queue-btn" style="padding:12px 24px;background:#dc2626;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">\ud83d\uddd1\ufe0f Clear Queue</button>
                </div>
                <iframe src="${url}" style="flex:1;width:100%;max-width:600px;border:none;border-radius:8px;background:white;"></iframe>
            `;
            document.getElementById('close-queue-btn').onclick = () => {
                overlay.style.display = 'none';
            };
            document.getElementById('clear-queue-btn').onclick = () => {
                localStorage.setItem('label_print_queue', '[]');
                this.updatePrintQueueBadge();
                overlay.style.display = 'none';
                URL.revokeObjectURL(url);
            };

            setTimeout(() => URL.revokeObjectURL(url), 300000);
        } catch (err) {
            alert('\u274c ' + err.message);
        }
    },

    async relocateLookupJob() {
        const jobInput = document.getElementById('relocate-job-number');
        const jobId = jobInput.value.trim();
        if (!jobId) return;

        const statusEl = document.getElementById('relocate-job-status');
        statusEl.className = 'status-message loading';
        statusEl.textContent = 'Looking up job materials...';
        statusEl.classList.remove('hidden');
        document.getElementById('relocate-job-info').classList.add('hidden');
        document.getElementById('relocate-materials-list').innerHTML = '';
        document.getElementById('relocate-selection-summary').classList.add('hidden');
        document.getElementById('to-relocate-dest-btn').disabled = true;

        try {
            const response = await fetch('/api/job-materials', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({jobId: jobId})
            });
            const data = await response.json();

            if (data.error) {
                statusEl.className = 'status-message error';
                statusEl.textContent = data.error;
                return;
            }

            this.relocateJobId = data.job.id;
            this.relocateJobNumber = data.job.number;
            this.relocateCustomer = data.job.customer;
            this.relocateItems = data.items || [];
            this.relocateSelectedItems = [];

            document.getElementById('relocate-job-title').textContent = `Job ${data.job.number} — ${data.job.customer}`;
            document.getElementById('relocate-job-customer').textContent = `${this.relocateItems.length} material(s) with assigned storage locations`;
            document.getElementById('relocate-job-info').classList.remove('hidden');

            if (this.relocateItems.length === 0) {
                statusEl.className = 'status-message error';
                statusEl.textContent = 'No assigned materials found on this job';
                return;
            }

            statusEl.classList.add('hidden');
            this.renderRelocateItems();

        } catch (error) {
            console.error('Relocate lookup error:', error);
            statusEl.className = 'status-message error';
            statusEl.textContent = 'Failed to look up job';
        }
    },

    renderRelocateItems() {
        const listEl = document.getElementById('relocate-materials-list');
        listEl.innerHTML = this.relocateItems.map((item, index) => `
            <div class="item-card">
                <label class="checkbox-label">
                    <input type="checkbox" onchange="app.toggleRelocateItem(${index})">
                    <span class="checkmark"></span>
                    <div class="item-details">
                        <strong>${item.partNo || 'No Part#'}</strong>
                        <span class="item-desc">${item.name || ''}</span>
                        <span class="item-location" style="color: #2196F3; font-weight: 600;">📍 ${item.currentStorage?.name || 'Unknown'} — Qty: ${item.qty}</span>
                        <span class="item-cc" style="color: #666; font-size: 12px;">CC: ${item.costCentreName || ''}</span>
                    </div>
                </label>
            </div>
        `).join('');

        document.getElementById('relocate-selection-summary').classList.remove('hidden');
        this.updateRelocateSelectionCount();
    },

    toggleRelocateItem(index) {
        const item = this.relocateItems[index];
        const idx = this.relocateSelectedItems.findIndex(i => i._index === index);
        if (idx >= 0) {
            this.relocateSelectedItems.splice(idx, 1);
        } else {
            this.relocateSelectedItems.push({...item, _index: index});
        }
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
        document.getElementById('relocate-dest-job-name').textContent = `Job ${this.relocateJobNumber}`;
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
        document.getElementById('processing-detail').textContent = `Moving ${this.relocateSelectedItems.length} item(s) to ${this.relocateDestName}`;

        try {
            const response = await fetch('/api/relocate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    jobId: this.relocateJobId,
                    jobNumber: this.relocateJobNumber,
                    customer: this.relocateCustomer,
                    destId: this.relocateDestId,
                    destName: this.relocateDestName,
                    items: this.relocateSelectedItems.map(item => ({
                        catalogId: item.catalogId,
                        qty: item.qty,
                        fromStorageId: item.currentStorage?.id,
                        fromStorageName: item.currentStorage?.name,
                        sectionId: item.sectionId,
                        costCentreId: item.costCentreId,
                        partNo: item.partNo,
                        name: item.name
                    }))
                })
            });

            const data = await response.json();

            if (data.error && !data.successCount) {
                alert('Relocate failed: ' + data.error);
                this.showScreen('relocate-dest');
                return;
            }

            this.relocateLabelItems = data.labelItems || [];

            document.getElementById('relocate-success-summary').textContent =
                `${data.successCount || 0} item(s) moved successfully` + (data.failCount ? ` (${data.failCount} failed)` : '');
            document.getElementById('relocate-success-from').textContent = `Job: ${this.relocateJobNumber}`;
            document.getElementById('relocate-success-to').textContent = `To: ${this.relocateDestName}`;
            document.getElementById('relocate-staff-name').textContent = data.movedBy || this.currentStaff?.displayName || 'Staff';

            this.showScreen('relocate-success');

        } catch (error) {
            console.error('Relocate error:', error);
            alert('Relocate failed: ' + error.message);
            this.showScreen('relocate-dest');
        }
    },

    async relocatePrintLabels() {
        if (!this.relocateLabelItems || this.relocateLabelItems.length === 0) {
            alert('No label data available');
            return;
        }

        const labels = this.relocateLabelItems.map(item => ({
            jobNumber: item.jobNumber || this.relocateJobNumber,
            customerName: item.customer || this.relocateCustomer,
            partCode: item.partNo,
            description: item.name,
            quantity: item.qty,
            storage: item.storage || this.relocateDestName,
            poNumber: 'RELOCATE',
            date: new Date().toLocaleDateString('en-AU')
        }));

        const isAndroid = /android/i.test(navigator.userAgent);

        if (isAndroid) {
            this._showAndroidLabels(labels, this.relocateLabelItems, 'RELOCATE');
        } else {
            this._showPdfLabels(labels, this.relocateLabelItems, 'RELOCATE');
        }
    },

    startNewRelocate() {
        this.relocateJobId = null;
        this.relocateJobNumber = null;
        this.relocateCustomer = null;
        this.relocateItems = [];
        this.relocateSelectedItems = [];
        this.relocateDestId = null;
        this.relocateDestName = null;
        this.relocateLabelItems = [];

        const jobInput = document.getElementById('relocate-job-number');
        if (jobInput) jobInput.value = '';
        document.getElementById('relocate-job-info')?.classList.add('hidden');
        document.getElementById('relocate-job-status')?.classList.add('hidden');
        document.getElementById('relocate-materials-list').innerHTML = '';
        document.getElementById('relocate-selection-summary')?.classList.add('hidden');

        this.showScreen('relocate-source');
    },
    
    // ============================================
    // Needs Receipting Dashboard
    // ============================================
    async loadReceiptingStatus() {
        try {
            const response = await fetch('/api/needs-receipting');
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
    
    showReportIssue() {
        const modal = document.getElementById('report-issue-modal');
        modal.classList.remove('hidden');
        
        // Pre-fill name and email from logged-in user
        const nameInput = document.getElementById('report-name');
        if (!nameInput.value) {
            const staffName = this.currentStaff?.displayName || document.getElementById('staff-name')?.textContent;
            if (staffName && staffName !== 'Staff') nameInput.value = staffName;
        }
        const emailInput = document.getElementById('report-email');
        if (!emailInput.value && this.currentStaff?.email) {
            emailInput.value = this.currentStaff.email;
        }
        
        // Auto-capture context
        this._captureContext();
        
        // Set up photo handlers (camera + library)
        const cameraInput = document.getElementById('report-photos-camera');
        const libraryInput = document.getElementById('report-photos-library');
        cameraInput.onchange = (e) => this._handleReportPhotos(e);
        libraryInput.onchange = (e) => this._handleReportPhotos(e);
        
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
        
        files.forEach(file => {
            const reader = new FileReader();
            reader.onload = (e) => {
                const base64 = e.target.result;
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
            };
            reader.readAsDataURL(file);
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
            const resp = await fetch('/api/report-fault', {
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
    // Allocate from Stock
    // ============================================
    async stockLookup() {
        const jobInput = document.getElementById('job-number');
        const jobId = jobInput.value.trim();
        if (!jobId) { alert('Enter a job number'); return; }
        
        const btn = document.getElementById('job-lookup-btn');
        const results = document.getElementById('stock-results');
        btn.disabled = true;
        btn.textContent = 'Searching...';
        results.innerHTML = '<p class="hint">Searching stock...</p>';
        
        try {
            const resp = await fetch('/api/job-stock-search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${this.token}` },
                body: JSON.stringify({ jobId })
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Search failed');
            }
            
            const data = await resp.json();
            this._stockJob = data.job;
            this._stockItems = data.items;
            
            if (!data.items || data.items.length === 0) {
                results.innerHTML = `<div class="card" style="padding:16px;text-align:center;">
                    <h3>Job ${data.job.id} — ${data.job.customer || data.job.number}</h3>
                    <p>${data.message || 'No unassigned items with available stock found.'}</p>
                </div>`;
                return;
            }
            
            // Build results UI
            let html = `<div class="card" style="padding:12px;margin-bottom:12px;">
                <h3 style="margin:0 0 4px;">Job ${data.job.id} — ${data.job.customer || ''}</h3>
                <p style="margin:0;color:#666;font-size:14px;">${data.job.number}</p>
            </div>`;
            
            html += '<div class="stock-items-list">';
            data.items.forEach((item, i) => {
                const bestLoc = item.stockLocations[0];
                html += `<div class="card" style="padding:12px;margin-bottom:8px;">
                    <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;">
                        <input type="checkbox" class="stock-item-cb" data-index="${i}" checked style="margin-top:4px;width:20px;height:20px;">
                        <div style="flex:1;">
                            <div style="font-weight:bold;font-size:14px;">${item.partNo}</div>
                            <div style="font-size:13px;color:#333;">${item.name}</div>
                            <div style="font-size:12px;color:#666;margin-top:4px;">
                                CC: ${item.costCentreName} | Need: ${item.neededQty}
                            </div>
                            <div style="margin-top:6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                                <label style="font-size:12px;font-weight:600;">Qty:</label>
                                <input type="number" class="stock-qty" data-index="${i}" value="${item.neededQty}" min="1" max="${bestLoc.availableQty}" 
                                    style="width:60px;padding:4px 8px;border:1px solid #ccc;border-radius:4px;font-size:14px;">
                                <label style="font-size:12px;font-weight:600;">From:</label>
                                <select class="stock-source" data-index="${i}" style="flex:1;min-width:120px;padding:4px;border:1px solid #ccc;border-radius:4px;font-size:13px;">
                                    ${item.stockLocations.map(loc => `<option value="${loc.storageId}" data-name="${loc.storageName}">${loc.storageName} (${loc.availableQty} avail)</option>`).join('')}
                                </select>
                            </div>
                        </div>
                    </label>
                </div>`;
            });
            html += '</div>';
            
            // Destination storage picker
            html += `<div class="card" style="padding:12px;margin-top:12px;">
                <h3 style="margin:0 0 8px;">Destination Storage</h3>
                <select id="stock-dest-storage" style="width:100%;padding:10px;border:1px solid #ccc;border-radius:6px;font-size:15px;">
                    <option value="">-- Select Destination --</option>
                    <optgroup label="Special Locations">
                        <option value="4" data-name="Customer Cupboard">Customer Cupboard</option>
                        <option value="21" data-name="Builders Cupboard">Builders Cupboard</option>
                    </optgroup>
                    <optgroup label="Container 1">
                        <option value="5" data-name="1.01">1.01</option>
                        <option value="6" data-name="1.02">1.02</option>
                        <option value="7" data-name="1.03">1.03</option>
                        <option value="8" data-name="1.04">1.04</option>
                    </optgroup>
                    <optgroup label="Container 2">
                        <option value="13" data-name="2.01">2.01</option>
                        <option value="14" data-name="2.02">2.02</option>
                        <option value="15" data-name="2.03">2.03</option>
                        <option value="16" data-name="2.04">2.04</option>
                    </optgroup>
                    <optgroup label="Container 3">
                        <option value="22" data-name="3.01">3.01</option>
                        <option value="23" data-name="3.02">3.02</option>
                    </optgroup>
                </select>
            </div>`;
            
            html += `<button id="stock-allocate-btn" class="btn btn-primary" style="width:100%;margin-top:12px;padding:14px;font-size:16px;">
                Allocate Selected Items
            </button>`;
            
            results.innerHTML = html;
            
            // Wire allocate button
            document.getElementById('stock-allocate-btn')?.addEventListener('click', () => this.allocateFromStockSubmit());
            
        } catch (err) {
            results.innerHTML = `<p class="hint" style="color:red;">Error: ${err.message}</p>`;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Look Up';
        }
    },

    async partSearch() {
        const input = document.getElementById('part-search');
        const query = input.value.trim();
        if (!query) { alert('Enter a part number'); return; }
        
        const btn = document.getElementById('part-search-btn');
        const results = document.getElementById('stock-results');
        btn.disabled = true;
        results.innerHTML = '<p class="hint">Searching...</p>';
        
        try {
            const resp = await fetch(`/api/stock-part-search?q=${encodeURIComponent(query)}`, {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (!resp.ok) throw new Error('Search failed');
            const data = await resp.json();
            if (!data.results || data.results.length === 0) {
                results.innerHTML = '<p class="hint">No items found matching that part number.</p>';
                return;
            }
            let html = '';
            data.results.forEach(item => {
                html += `<div class="card" style="padding:12px;margin-bottom:8px;">
                    <div style="font-weight:bold;">${item.partNo || ''}</div>
                    <div style="font-size:13px;">${item.name || ''}</div>
                    <div style="font-size:12px;color:#666;">Stock: ${item.availableQty || 0} in ${item.storageName || 'Unknown'}</div>
                </div>`;
            });
            results.innerHTML = html;
        } catch (err) {
            results.innerHTML = `<p class="hint" style="color:red;">Error: ${err.message}</p>`;
        } finally {
            btn.disabled = false;
        }
    },

    async allocateFromStockSubmit() {
        const destSelect = document.getElementById('stock-dest-storage');
        const destId = destSelect.value;
        const destName = destSelect.options[destSelect.selectedIndex]?.dataset?.name || destSelect.options[destSelect.selectedIndex]?.text || '';
        
        if (!destId) { alert('Select a destination storage location'); return; }
        if (!this._stockJob || !this._stockItems) { alert('No items loaded'); return; }
        
        // Gather checked items
        const checkboxes = document.querySelectorAll('.stock-item-cb:checked');
        if (checkboxes.length === 0) { alert('Select at least one item'); return; }
        
        const items = [];
        checkboxes.forEach(cb => {
            const idx = parseInt(cb.dataset.index);
            const item = this._stockItems[idx];
            const qtyInput = document.querySelector(`.stock-qty[data-index="${idx}"]`);
            const srcSelect = document.querySelector(`.stock-source[data-index="${idx}"]`);
            const srcOpt = srcSelect.options[srcSelect.selectedIndex];
            
            items.push({
                catalogId: item.catalogId,
                name: item.name,
                partNo: item.partNo,
                quantity: parseInt(qtyInput.value) || item.neededQty,
                sourceStorageId: parseInt(srcSelect.value),
                sourceStorageName: srcOpt.dataset.name || srcOpt.text,
                sectionId: item.sectionId,
                costCentreId: item.costCentreId
            });
        });
        
        const allocBtn = document.getElementById('stock-allocate-btn');
        allocBtn.disabled = true;
        allocBtn.textContent = 'Allocating...';
        
        try {
            const resp = await fetch('/api/allocate-from-stock', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${this.token}` },
                body: JSON.stringify({
                    jobId: this._stockJob.id,
                    destinationStorageId: parseInt(destId),
                    destinationStorageName: destName,
                    items
                })
            });
            
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || 'Allocation failed');
            
            const successCount = data.successCount || 0;
            const totalCount = data.totalCount || items.length;
            
            // Show results
            let resultHtml = `<div class="card" style="padding:16px;text-align:center;">
                <h3 style="color:${successCount === totalCount ? '#22c55e' : '#f59e0b'};">
                    ${successCount === totalCount ? '✅' : '⚠️'} ${successCount}/${totalCount} items allocated
                </h3>`;
            
            if (data.results) {
                data.results.forEach(r => {
                    const icon = r.success ? '✅' : '❌';
                    resultHtml += `<div style="text-align:left;padding:4px 0;font-size:13px;">
                        ${icon} ${r.partNo || ''} — ${r.success ? (r.message || 'OK') : (r.error || 'Failed')}
                    </div>`;
                });
            }
            
            resultHtml += `<button class="btn btn-primary" style="margin-top:12px;padding:10px 24px;" onclick="document.getElementById('stock-results').innerHTML='<p class=hint>Enter a job number to see items available in stock</p>';document.getElementById('job-number').value='';">
                Done — New Lookup
            </button>`;
            
            // Print labels button if any succeeded
            if (successCount > 0) {
                resultHtml += `<button class="btn btn-secondary" style="margin-top:8px;padding:10px 24px;" id="stock-print-labels-btn">
                    🏷️ Print Labels
                </button>`;
            }
            
            resultHtml += '</div>';
            document.getElementById('stock-results').innerHTML = resultHtml;
            
            // Wire print labels
            if (successCount > 0) {
                document.getElementById('stock-print-labels-btn')?.addEventListener('click', () => {
                    const labelItems = items.filter((_, i) => data.results[i]?.success).map(it => ({
                        jobNumber: this._stockJob.id,
                        customerName: this._stockJob.customer || '',
                        partNo: it.partNo,
                        description: it.name,
                        quantity: it.quantity,
                        storageLocation: destName
                    }));
                    this.generateAndShowLabels(labelItems, `Stock-J${this._stockJob.id}`);
                });
            }
            
        } catch (err) {
            alert('Allocation error: ' + err.message);
            allocBtn.disabled = false;
            allocBtn.textContent = 'Allocate Selected Items';
        }
    },

    // ============================================
    // Utilities
    // ============================================
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


// ============================================================
// CUSTOMER COLLECTION MODULE
// ============================================================
(function() {
    const cState = {
        jobNumber: null, jobId: null, jobName: '',
        customer: {}, materials: [], history: [],
        selectedItems: [], photos: [], signatureData: null
    };
    let sigCtx = null, sigDrawing = false, sigHasData = false;

    // --- LOOKUP ---
    document.getElementById('collection-lookup-btn')?.addEventListener('click', collectionLookup);
    document.getElementById('collection-job-input')?.addEventListener('keydown', e => {
        if (e.key === 'Enter') collectionLookup();
    });

    async function collectionLookup() {
        const input = document.getElementById('collection-job-input');
        const status = document.getElementById('collection-status');
        const resultsDiv = document.getElementById('collection-search-results');
        const query = input.value.trim();
        if (!query) { input.focus(); return; }

        status.classList.remove('hidden');
        status.className = 'status-message info';
        status.textContent = 'Searching...';
        resultsDiv.classList.add('hidden');
        resultsDiv.innerHTML = '';

        try {
            const resp = await fetch(`/api/collection/job-lookup?q=${encodeURIComponent(query)}`);
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || 'Lookup failed');

            if (data.multiple) {
                status.classList.add('hidden');
                resultsDiv.classList.remove('hidden');
                resultsDiv.innerHTML = '<h3 class="section-title">Select a Job</h3>' +
                    data.jobs.map(j => `<div class="po-item" style="cursor:pointer;padding:12px" onclick="window._selectCollectionJob(${j.id})">
                        <div style="font-weight:700;font-size:15px">Job ${j.id} - ${escH(j.name)}</div>
                        <div style="font-size:13px;color:#666">${escH(j.customer_name)}</div>
                        ${j.customer_phone ? '<div style="font-size:12px;color:#888">Ph: ' + escH(j.customer_phone) + '</div>' : ''}
                    </div>`).join('');
                return;
            }

            cState.jobNumber = String(data.job.id);
            cState.jobId = data.job.id;
            cState.jobName = data.job.name;
            cState.customer = data.customer;
            cState.materials = data.materials;
            cState.history = data.history;
            status.classList.add('hidden');
            renderCollectionDetails();
            app.showScreen('collection-details');
        } catch(e) {
            status.className = 'status-message error';
            status.textContent = e.message;
        }
    }

    window._selectCollectionJob = async function(jobId) {
        const status = document.getElementById('collection-status');
        const resultsDiv = document.getElementById('collection-search-results');
        status.classList.remove('hidden');
        status.className = 'status-message info';
        status.textContent = 'Loading job details...';
        resultsDiv.classList.add('hidden');
        try {
            const resp = await fetch(`/api/collection/job-lookup?q=${jobId}`);
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || 'Lookup failed');
            cState.jobNumber = String(data.job.id);
            cState.jobId = data.job.id;
            cState.jobName = data.job.name;
            cState.customer = data.customer;
            cState.materials = data.materials;
            cState.history = data.history;
            status.classList.add('hidden');
            renderCollectionDetails();
            app.showScreen('collection-details');
        } catch(e) {
            status.className = 'status-message error';
            status.textContent = e.message;
        }
    };

    function escH(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

    function renderCollectionDetails() {
        const c = cState.customer;
        document.getElementById('collection-customer-card').innerHTML = `
            <h2>Job ${escH(cState.jobNumber)}</h2>
            <p class="vendor-name">${escH(cState.jobName)}</p>
            <p class="vendor-name">${escH(c.name || 'Unknown Customer')}</p>
            ${c.phone ? '<p style="font-size:13px;color:#666;margin:2px 0">Ph: ' + escH(c.phone) + '</p>' : ''}
            ${c.address ? '<p style="font-size:13px;color:#888;margin:2px 0">' + escH(c.address) + '</p>' : ''}
        `;

        const list = document.getElementById('collection-materials-list');
        if (!cState.materials.length) {
            list.innerHTML = '<p style="color:#888;text-align:center">No materials found on this job</p>';
            document.getElementById('collection-next-btn').disabled = true;
            return;
        }

        list.innerHTML = cState.materials.map((m, i) => {
            const remaining = m.remaining != null ? m.remaining : m.assigned;
            const collected = m.collected || 0;
            const fullyDone = remaining <= 0;
            const badgeCls = fullyDone ? 'done' : collected > 0 ? 'partial' : 'available';
            const badgeTxt = fullyDone ? 'Collected' : collected > 0 ? collected + ' collected' : 'Available';
            return '<div class="collection-item ' + (fullyDone ? 'collected' : '') + '">'
                + '<input type="checkbox" class="ci-check" data-idx="' + i + '"' + (fullyDone ? ' disabled' : '') + '>'
                + '<div class="ci-info">'
                + '<div class="ci-part">' + escH(m.partCode) + '</div>'
                + '<div class="ci-desc">' + escH(m.description) + '</div>'
                + '<div class="ci-loc">' + escH(m.storage || 'Unknown') + (m.costCentreName ? ' | ' + escH(m.costCentreName) : '') + '</div>'
                + '<span class="ci-badge ' + badgeCls + '">' + badgeTxt + '</span>'
                + '</div>'
                + '<div class="ci-qty">'
                + '<input type="number" class="ci-qty-input" data-idx="' + i + '" value="' + remaining + '" min="1" max="' + remaining + '"' + (fullyDone ? ' disabled' : '') + '>'
                + '<span class="ci-qty-label">of ' + m.assigned + '</span>'
                + '</div></div>';
        }).join('');

        list.querySelectorAll('.ci-check').forEach(cb => cb.addEventListener('change', updateSel));

        const selAll = document.getElementById('collection-select-all-cb');
        if (selAll) {
            selAll.checked = false;
            selAll.onchange = function() {
                list.querySelectorAll('.ci-check:not(:disabled)').forEach(cb => { cb.checked = this.checked; });
                updateSel();
            };
        }

        // History
        const histSec = document.getElementById('collection-history-section');
        const histList = document.getElementById('collection-history-list');
        if (cState.history.length) {
            histSec.style.display = 'block';
            histList.innerHTML = cState.history.map(h => {
                const d = h.date ? new Date(h.date) : null;
                const ds = d ? d.toLocaleDateString('en-AU', {day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
                const its = (h.items||[]).map(it => it.description + ' x' + it.quantity).join(', ');
                return '<div class="collection-history-item">'
                    + '<div class="ch-header"><span>' + escH(h.collectedBy) + '</span><span>' + ds + '</span></div>'
                    + '<div class="ch-items">' + escH(its) + '</div>'
                    + (h.notes ? '<div class="ch-notes">' + escH(h.notes) + '</div>' : '')
                    + '<div style="font-size:11px;color:#aaa">Staff: ' + escH(h.staffName||'') + (h.vehicleRego ? ' | Rego: ' + escH(h.vehicleRego) : '') + '</div>'
                    + '</div>';
            }).join('');
        } else {
            histSec.style.display = 'none';
        }
        updateSel();
    }

    function updateSel() {
        const checks = document.querySelectorAll('#collection-materials-list .ci-check:checked');
        const btn = document.getElementById('collection-next-btn');
        btn.disabled = checks.length === 0;
        btn.textContent = checks.length ? 'Collect ' + checks.length + ' Item' + (checks.length > 1 ? 's' : '') + ' \u2192' : 'Collect Selected Items \u2192';
    }

    // --- NEXT: CONFIRM SCREEN ---
    document.getElementById('collection-next-btn')?.addEventListener('click', () => {
        const checks = document.querySelectorAll('#collection-materials-list .ci-check:checked');
        cState.selectedItems = [];
        checks.forEach(cb => {
            const idx = parseInt(cb.dataset.idx);
            const m = cState.materials[idx];
            const qtyInput = document.querySelector('.ci-qty-input[data-idx="' + idx + '"]');
            const qty = parseInt(qtyInput.value) || 0;
            if (qty > 0) cState.selectedItems.push(Object.assign({}, m, { collectQty: qty }));
        });
        if (!cState.selectedItems.length) return;
        renderConfirm();
        app.showScreen('collection-confirm');
        setTimeout(initSigCanvas, 100);
    });

    function renderConfirm() {
        document.getElementById('collection-confirm-items').innerHTML = cState.selectedItems.map(it =>
            '<div class="confirm-item"><span>' + escH(it.partCode) + ' \u2014 ' + escH(it.description) + '</span><strong>x' + it.collectQty + '</strong></div>'
        ).join('');
        cState.photos = [];
        document.getElementById('collection-photo-previews').innerHTML = '';
        document.getElementById('collection-person').value = '';
        document.getElementById('collection-vehicle').value = '';
        document.getElementById('collection-notes').value = '';
        validateComplete();
    }

    // --- SIGNATURE ---
    function initSigCanvas() {
        const canvas = document.getElementById('sig-canvas');
        if (!canvas) return;
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = Math.floor(rect.width - 4) * 2;
        canvas.height = 300;
        canvas.style.height = '150px';
        sigCtx = canvas.getContext('2d');
        sigCtx.strokeStyle = '#000';
        sigCtx.lineWidth = 2;
        sigCtx.lineCap = 'round';
        sigCtx.lineJoin = 'round';
        sigHasData = false;
        sigDrawing = false;
        sigCtx.clearRect(0, 0, canvas.width, canvas.height);

        function gp(e) {
            const r = canvas.getBoundingClientRect();
            const sx = canvas.width / r.width, sy = canvas.height / r.height;
            const t = e.touches ? e.touches[0] : e;
            return { x: (t.clientX - r.left) * sx, y: (t.clientY - r.top) * sy };
        }
        function sd(e) { e.preventDefault(); sigDrawing = true; const p = gp(e); sigCtx.beginPath(); sigCtx.moveTo(p.x, p.y); }
        function md(e) { if (!sigDrawing) return; e.preventDefault(); const p = gp(e); sigCtx.lineTo(p.x, p.y); sigCtx.stroke(); sigHasData = true; validateComplete(); }
        function ed() { sigDrawing = false; }

        canvas.onmousedown = sd; canvas.onmousemove = md; canvas.onmouseup = ed; canvas.onmouseleave = ed;
        canvas.ontouchstart = sd; canvas.ontouchmove = md; canvas.ontouchend = ed;

        document.getElementById('sig-clear-btn').onclick = () => {
            sigCtx.clearRect(0, 0, canvas.width, canvas.height);
            sigHasData = false; validateComplete();
        };
    }

    // --- PHOTOS ---
    function handlePhotos(e) {
        Array.from(e.target.files).forEach(file => {
            const reader = new FileReader();
            reader.onload = ev => { cState.photos.push(ev.target.result); renderThumbs(); };
            reader.readAsDataURL(file);
        });
        e.target.value = '';
    }
    document.getElementById('collection-photo-input')?.addEventListener('change', handlePhotos);
    document.getElementById('collection-photo-library')?.addEventListener('change', handlePhotos);

    function renderThumbs() {
        const el = document.getElementById('collection-photo-previews');
        el.innerHTML = cState.photos.map((p, i) =>
            '<div class="photo-thumb"><img src="' + p + '"><button class="photo-remove" data-idx="' + i + '">&times;</button></div>'
        ).join('');
        el.querySelectorAll('.photo-remove').forEach(btn => {
            btn.onclick = () => { cState.photos.splice(parseInt(btn.dataset.idx), 1); renderThumbs(); };
        });
    }

    // --- VALIDATE ---
    function validateComplete() {
        const name = document.getElementById('collection-person')?.value.trim();
        document.getElementById('collection-complete-btn').disabled = !(name && sigHasData);
    }
    document.getElementById('collection-person')?.addEventListener('input', validateComplete);

    // --- COMPLETE ---
    document.getElementById('collection-complete-btn')?.addEventListener('click', doComplete);

    async function doComplete() {
        const btn = document.getElementById('collection-complete-btn');
        btn.disabled = true; btn.textContent = 'Saving...';

        const canvas = document.getElementById('sig-canvas');
        cState.signatureData = canvas.toDataURL('image/png');

        const payload = {
            jobNumber: cState.jobNumber, jobId: cState.jobId, jobName: cState.jobName,
            customerName: cState.customer.name || '',
            customerEmail: cState.customer.email || '',
            customerPhone: cState.customer.phone || '',
            siteAddress: cState.customer.address || '',
            collectedBy: document.getElementById('collection-person').value.trim(),
            vehicleRego: document.getElementById('collection-vehicle').value.trim(),
            notes: document.getElementById('collection-notes').value.trim(),
            signatureData: cState.signatureData,
            items: cState.selectedItems.map(it => ({
                catalogId: it.catalogId, partCode: it.partCode,
                description: it.description, quantity: it.collectQty,
                storage: it.storage, storageId: it.storageId
            })),
            photos: cState.photos
        };

        try {
            const resp = await fetch('/api/collection/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || 'Failed');

            document.getElementById('collection-success-summary').innerHTML =
                '<div class="success-summary">'
                + '<h3>Job ' + escH(payload.jobNumber) + ' \u2014 ' + escH(payload.jobName) + '</h3>'
                + '<div class="ss-line"><strong>Collected by:</strong> ' + escH(payload.collectedBy) + '</div>'
                + (payload.vehicleRego ? '<div class="ss-line"><strong>Vehicle:</strong> ' + escH(payload.vehicleRego) + '</div>' : '')
                + '<div class="ss-line"><strong>Items:</strong></div>'
                + payload.items.map(it => '<div class="ss-line">\u2022 ' + escH(it.description) + ' \u00d7 ' + it.quantity + '</div>').join('')
                + (payload.customerEmail ? '<div class="ss-line" style="margin-top:8px">Confirmation email sent to ' + escH(payload.customerEmail) + '</div>' : '')
                + '<div class="ss-line" style="margin-top:8px;color:#888">Collection #' + data.collectionId + '</div>'
                + '</div>';
            app.showScreen('collection-success');
        } catch(e) {
            alert('Error: ' + e.message);
            btn.disabled = false;
            btn.textContent = 'Complete Collection';
        }
    }
})();

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
    relocateSourceId: null,
    relocateSourceName: null,
    relocateItems: [],
    relocateSelectedItems: [],
    relocateDestId: null,
    relocateDestName: null,
    
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
        document.getElementById('mystery-search')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.searchMysteryBox();
        });
        document.getElementById('option-labels')?.addEventListener('click', () => this.showScreen('labels'));
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
        document.getElementById('to-storage-btn')?.addEventListener('click', () => this.showScreen('storage'));
        
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
                               min="0" max="${remaining}" value="${remaining}"
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
    
    reprintLabels() {
        // Build labels for all allocated items in this PO
        const container = document.getElementById('label-print-container');
        if (!container) return;
        
        const po = this.currentPO;
        const today = new Date().toLocaleDateString('en-AU');
        container.innerHTML = '';
        
        let labelCount = 0;
        po.items.forEach(item => {
            if (!item.storageLocation || item.storageLocation === 'Stock Holding') return;
            
            const qty = item.quantityReceived || item.quantityOrdered;
            for (let i = 0; i < qty; i++) {
                const label = document.createElement('div');
                label.className = 'print-label';
                label.innerHTML = `
                    <div class="label-row-top">
                        <span class="label-job">${item.jobNumber ? 'Job ' + item.jobNumber : ''}</span>
                        <span class="label-customer">${item.customerName || ''}</span>
                        <span class="label-separator">│</span>
                        <span class="label-partno">${item.partNo || ''}</span>
                        <span class="label-desc">${item.description}</span>
                    </div>
                    <div class="label-row-bottom">
                        <span class="label-qty">Qty: ${qty}</span>
                        <span class="label-location">${item.storageLocation}</span>
                        <span class="label-date">${today}</span>
                        <span class="label-po">PO ${po.poNumber}</span>
                    </div>
                `;
                container.appendChild(label);
                labelCount++;
            }
        });
        
        if (labelCount === 0) {
            alert('No allocated items to print labels for.');
            return;
        }
        
        window.print();
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
    
    printLabelsFromScreen() {
        if (!this.labelPO) return;
        
        const container = document.getElementById('label-print-container');
        if (!container) return;
        
        const po = this.labelPO;
        const today = new Date().toLocaleDateString('en-AU');
        container.innerHTML = '';
        
        let labelCount = 0;
        po.items.forEach(item => {
            if (!item.storageLocation || item.storageLocation === 'Stock Holding') return;
            
            const qty = item.quantityReceived || item.quantityOrdered;
            for (let i = 0; i < qty; i++) {
                const label = document.createElement('div');
                label.className = 'print-label';
                label.innerHTML = `
                    <div class="label-row-top">
                        <span class="label-job">${item.jobNumber ? 'Job ' + item.jobNumber : ''}</span>
                        <span class="label-customer">${item.customerName || ''}</span>
                        <span class="label-separator">│</span>
                        <span class="label-partno">${item.partNo || ''}</span>
                        <span class="label-desc">${item.description}</span>
                    </div>
                    <div class="label-row-bottom">
                        <span class="label-qty">Qty: ${qty}</span>
                        <span class="label-location">${item.storageLocation}</span>
                        <span class="label-date">${today}</span>
                        <span class="label-po">PO ${po.poNumber}</span>
                    </div>
                `;
                container.appendChild(label);
                labelCount++;
            }
        });
        
        if (labelCount === 0) {
            alert('No allocated items to print labels for.');
            return;
        }
        
        window.print();
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
        let qty = parseInt(qtyInput.value) || 0;
        if (qty < 0) qty = 0;
        if (qty > remaining) qty = remaining;
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
                const qty = qtyInput ? parseInt(qtyInput.value) || remaining : remaining;
                this.selectedItems.push({
                    index,
                    catalogId: item.catalogId,
                    description: item.description,
                    partNo: item.partNo,
                    quantity: qty,
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
    printLabels() {
        // Generate labels - one sticker per item
        const container = document.getElementById('label-print-container');
        container.innerHTML = '';
        
        const dateStr = new Date().toLocaleDateString();
        const storageLocation = this.selectedStorage?.name || this._lastStorageName || 'Unknown';
        const poNumber = this.currentPO?.poNumber || 'N/A';
        // PO-level fallbacks (used if item doesn't have per-item job)
        const poJobNumber = this.currentPO?.jobNumber || 'N/A';
        const poCustomerName = this.currentPO?.customerName || 'N/A';
        
        this.selectedItems.forEach(item => {
            const label = document.createElement('div');
            label.className = 'print-label';
            const itemJob = item.jobNumber || poJobNumber;
            const itemCustomer = item.customerName || poCustomerName;
            label.innerHTML = `
                <div class="label-row label-row-top">
                    <span class="label-job">Job ${itemJob}</span>
                    <span class="label-customer">${itemCustomer}</span>
                    <span class="label-partno">${item.partNo || ''}</span>
                    <span class="label-desc">${item.description}</span>
                </div>
                <div class="label-row label-row-bottom">
                    <span class="label-qty">Qty: ${item.quantity}</span>
                    <span class="label-location">${storageLocation}</span>
                    <span class="label-date">${dateStr}</span>
                    <span class="label-po">PO ${poNumber}</span>
                </div>
            `;
            container.appendChild(label);
        });
        
        window.print();
    },
    
    // ============================================
    // Relocate Stock
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
            if (destId === this.relocateSourceId) {
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
            const response = await fetch('/api/relocate', {
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

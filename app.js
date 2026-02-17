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
    
    // Staff state
    currentStaff: null,
    staffList: [],
    editingStaffId: null,
    
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
        
        // Render items
        const itemsList = document.getElementById('items-list');
        this.selectedItems = [];
        
        itemsList.innerHTML = this.currentPO.items.map((item, index) => {
            const statusClass = item.receiptStatus === 'fully_receipted' ? 'receipted' 
                : item.receiptStatus === 'partially_receipted' ? 'partial' : 'pending';
            const statusText = item.receiptStatus === 'fully_receipted' ? 'Fully receipted'
                : item.receiptStatus === 'partially_receipted' ? 'Partially receipted' : 'Not yet receipted';
            
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
                            <span class="item-qty">Ordered: ${item.quantityOrdered}</span>
                            <span class="item-received">Received: ${item.quantityReceived}</span>
                        </div>
                        <div class="item-status ${statusClass}">${statusText}</div>
                    </div>
                </div>
            `;
        }).join('');
        
        this.updateSelectionCount();
        this.showScreen('verify');
    },
    
    toggleItem(index) {
        const item = this.currentPO.items[index];
        const idx = this.selectedItems.findIndex(i => i.index === index);
        
        if (idx >= 0) {
            this.selectedItems.splice(idx, 1);
        } else {
            this.selectedItems.push({
                index,
                catalogId: item.catalogId,
                description: item.description,
                partNo: item.partNo,
                quantity: item.quantityOrdered - item.quantityReceived
            });
        }
        
        this.updateSelectionCount();
    },
    
    toggleSelectAll(event) {
        const checked = event.target.checked;
        const checkboxes = document.querySelectorAll('#items-list input[type="checkbox"]');
        
        this.selectedItems = [];
        
        checkboxes.forEach((cb, index) => {
            cb.checked = checked;
            if (checked) {
                const item = this.currentPO.items[index];
                this.selectedItems.push({
                    index,
                    catalogId: item.catalogId,
                    description: item.description,
                    partNo: item.partNo,
                    quantity: item.quantityOrdered - item.quantityReceived
                });
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
                        quantity: item.quantity
                    })),
                    storageDeviceId: this.selectedStorage.id,
                    storageName: this.selectedStorage.name
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
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
        
        // Label count
        const totalLabels = this.selectedItems.reduce((sum, item) => sum + item.quantity, 0);
        document.getElementById('label-count').textContent = `${totalLabels} labels ready to print`;
        
        this.showScreen('success');
    },
    
    startNewPO() {
        this.currentPO = null;
        this.selectedItems = [];
        this.selectedStorage = null;
        document.getElementById('po-number').value = '';
        document.getElementById('storage-dropdown').value = '';
        document.getElementById('allocate-btn').disabled = true;
        document.getElementById('select-all').checked = false;
        this.showScreen('scan');
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
    handleDocketPhoto(event) {
        const file = event.target.files[0];
        if (file) {
            // For now just show PO input - OCR would extract PO number
            this.showStatus('scan-status', 'Photo captured. Enter PO number to continue.', 'success');
        }
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
        // Generate labels
        const container = document.getElementById('label-print-container');
        container.innerHTML = '';
        
        const dateStr = new Date().toLocaleDateString();
        
        this.selectedItems.forEach(item => {
            for (let i = 0; i < item.quantity; i++) {
                const label = document.createElement('div');
                label.className = 'label';
                label.innerHTML = `
                    <div class="label-line1">${this.currentPO.jobNumber || 'N/A'} - ${this.currentPO.customerName || 'Customer'} - ${item.partNo || 'N/A'}</div>
                    <div class="label-line2">${item.description} - ${dateStr}</div>
                `;
                container.appendChild(label);
            }
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

#!/usr/bin/env python3
"""
PO Receiving App - Backend Server
With Staff Management System
"""

import os
import json
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session
import requests

app = Flask(__name__, static_folder='.')
app.secret_key = secrets.token_hex(32)

# ============================================
# Configuration
# ============================================
SIMPRO_BASE_URL = "https://2ndfix.simprosuite.com/api/v1.0"
SIMPRO_TOKEN_URL = "https://2ndfix.simprosuite.com/oauth2/token"
SIMPRO_CLIENT_ID = "ea496c1b064ff70c39662ecf85ddf4"
SIMPRO_CLIENT_SECRET = "9e02a6282c"
COMPANY_ID = 3

# Database file
DB_FILE = os.path.join(os.path.dirname(__file__), 'staff.db')

# Token cache
token_cache = {
    'access_token': None,
    'expires_at': None
}

# ============================================
# Database Setup
# ============================================
def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Staff table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff' CHECK(role IN ('admin', 'manager', 'staff')),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    
    # Allocation logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS allocation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL,
            staff_name TEXT NOT NULL,
            po_number TEXT,
            job_number TEXT,
            vendor_name TEXT,
            items_allocated INTEGER,
            storage_location TEXT,
            allocation_type TEXT,
            verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        )
    ''')
    
    conn.commit()
    
    # Check if any admin exists, if not create default
    cursor.execute("SELECT COUNT(*) FROM staff WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        # Create default admin (George)
        default_password = hash_password('2ndFix2026')
        cursor.execute('''
            INSERT INTO staff (username, display_name, password_hash, role, active)
            VALUES (?, ?, ?, ?, ?)
        ''', ('george', 'George', default_password, 'admin', 1))
        conn.commit()
        print("Created default admin account: george")
    
    conn.close()

def hash_password(password):
    """Hash a password with salt"""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}:{hash_obj.hex()}"

def verify_password(password, password_hash):
    """Verify a password against its hash"""
    try:
        salt, hash_hex = password_hash.split(':')
        hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return hash_obj.hex() == hash_hex
    except:
        return False

# ============================================
# Authentication Decorators
# ============================================
def login_required(f):
    """Require staff login"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'staff_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        return f(*args, **kwargs)
    return decorated

def manager_required(f):
    """Require manager or admin role"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'staff_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        if session.get('role') not in ('admin', 'manager'):
            return jsonify({'error': 'Manager access required'}), 403
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """Require admin role"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'staff_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

# ============================================
# Staff Authentication Endpoints
# ============================================
@app.route('/api/auth/login', methods=['POST'])
def staff_login():
    """Staff login endpoint"""
    data = request.get_json()
    username = data.get('username', '').lower().strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM staff WHERE username = ? AND active = 1', (username,))
    staff = cursor.fetchone()
    conn.close()
    
    if not staff or not verify_password(password, staff['password_hash']):
        return jsonify({'error': 'Invalid username or password'}), 401
    
    # Set session
    session['staff_id'] = staff['id']
    session['username'] = staff['username']
    session['display_name'] = staff['display_name']
    session['role'] = staff['role']
    
    return jsonify({
        'success': True,
        'staff': {
            'id': staff['id'],
            'username': staff['username'],
            'displayName': staff['display_name'],
            'role': staff['role']
        }
    })

@app.route('/api/auth/logout', methods=['POST'])
def staff_logout():
    """Staff logout endpoint"""
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Check authentication status"""
    if 'staff_id' in session:
        return jsonify({
            'authenticated': True,
            'staff': {
                'id': session['staff_id'],
                'username': session['username'],
                'displayName': session['display_name'],
                'role': session['role']
            }
        })
    return jsonify({'authenticated': False})

# ============================================
# Staff Management Endpoints
# ============================================
@app.route('/api/staff', methods=['GET'])
@manager_required
def list_staff():
    """List all staff members"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, display_name, role, active, created_at FROM staff ORDER BY display_name')
    staff_list = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'staff': staff_list})

@app.route('/api/staff', methods=['POST'])
@manager_required
def add_staff():
    """Add new staff member"""
    data = request.get_json()
    
    username = data.get('username', '').lower().strip()
    display_name = data.get('displayName', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'staff')
    
    # Validation
    if not username or not display_name or not password:
        return jsonify({'error': 'Username, display name, and password required'}), 400
    
    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400
    
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    
    # Only admins can create managers/admins
    if role in ('admin', 'manager') and session.get('role') != 'admin':
        return jsonify({'error': 'Only admins can create manager accounts'}), 403
    
    if role not in ('admin', 'manager', 'staff'):
        role = 'staff'
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if username exists
    cursor.execute('SELECT id FROM staff WHERE username = ?', (username,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': 'Username already exists'}), 400
    
    # Create staff
    password_hash = hash_password(password)
    cursor.execute('''
        INSERT INTO staff (username, display_name, password_hash, role, active)
        VALUES (?, ?, ?, ?, 1)
    ''', (username, display_name, password_hash, role))
    
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'staff': {
            'id': new_id,
            'username': username,
            'displayName': display_name,
            'role': role,
            'active': 1
        }
    })

@app.route('/api/staff/<int:staff_id>', methods=['PUT'])
@manager_required
def update_staff(staff_id):
    """Update staff member"""
    data = request.get_json()
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get current staff
    cursor.execute('SELECT * FROM staff WHERE id = ?', (staff_id,))
    staff = cursor.fetchone()
    
    if not staff:
        conn.close()
        return jsonify({'error': 'Staff not found'}), 404
    
    # Non-admins can't modify admins/managers
    if staff['role'] in ('admin', 'manager') and session.get('role') != 'admin':
        conn.close()
        return jsonify({'error': 'Only admins can modify manager accounts'}), 403
    
    # Build update
    updates = []
    params = []
    
    if 'displayName' in data:
        updates.append('display_name = ?')
        params.append(data['displayName'].strip())
    
    if 'password' in data and data['password']:
        if len(data['password']) < 6:
            conn.close()
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        updates.append('password_hash = ?')
        params.append(hash_password(data['password']))
    
    if 'role' in data:
        if session.get('role') != 'admin':
            conn.close()
            return jsonify({'error': 'Only admins can change roles'}), 403
        if data['role'] in ('admin', 'manager', 'staff'):
            updates.append('role = ?')
            params.append(data['role'])
    
    if 'active' in data:
        # Prevent disabling yourself
        if staff_id == session.get('staff_id') and not data['active']:
            conn.close()
            return jsonify({'error': 'Cannot disable your own account'}), 400
        updates.append('active = ?')
        params.append(1 if data['active'] else 0)
    
    if updates:
        updates.append('updated_at = datetime("now")')
        params.append(staff_id)
        cursor.execute(f'UPDATE staff SET {", ".join(updates)} WHERE id = ?', params)
        conn.commit()
    
    conn.close()
    return jsonify({'success': True})

@app.route('/api/staff/<int:staff_id>', methods=['DELETE'])
@admin_required
def delete_staff(staff_id):
    """Delete staff member (admin only)"""
    if staff_id == session.get('staff_id'):
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM staff WHERE id = ?', (staff_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

# ============================================
# Allocation Logs Endpoint
# ============================================
@app.route('/api/logs', methods=['GET'])
@manager_required
def get_allocation_logs():
    """Get allocation logs (managers only)"""
    limit = request.args.get('limit', 50, type=int)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM allocation_logs 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (limit,))
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify({'logs': logs})

def log_allocation(staff_id, staff_name, po_number, job_number, vendor_name, items_count, storage_location, allocation_type, verified):
    """Log an allocation"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO allocation_logs 
        (staff_id, staff_name, po_number, job_number, vendor_name, items_allocated, storage_location, allocation_type, verified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (staff_id, staff_name, po_number, job_number, vendor_name, items_count, storage_location, allocation_type, verified))
    conn.commit()
    conn.close()

# ============================================
# Simpro API Functions
# ============================================
def get_simpro_token(force_refresh=False):
    """Get valid Simpro OAuth token with automatic refresh"""
    # Check if we have a valid cached token
    if not force_refresh and token_cache['access_token'] and token_cache['expires_at']:
        if datetime.now() < token_cache['expires_at']:
            return token_cache['access_token']
    
    # Clear cache before refresh attempt
    token_cache['access_token'] = None
    token_cache['expires_at'] = None
    
    print(f"[{datetime.now()}] Refreshing Simpro API token...")
    
    try:
        response = requests.post(SIMPRO_TOKEN_URL, data={
            'grant_type': 'client_credentials',
            'client_id': SIMPRO_CLIENT_ID,
            'client_secret': SIMPRO_CLIENT_SECRET
        }, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            token_cache['access_token'] = data['access_token']
            # Refresh 5 minutes before expiry to be safe
            token_cache['expires_at'] = datetime.now() + timedelta(seconds=data.get('expires_in', 3600) - 300)
            print(f"[{datetime.now()}] Token refreshed successfully, expires at {token_cache['expires_at']}")
            return token_cache['access_token']
        else:
            print(f"[{datetime.now()}] Token refresh failed: {response.status_code} - {response.text}")
            raise Exception(f"Failed to get token: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now()}] Token refresh error: {e}")
        raise Exception(f"Token refresh failed: {e}")

def simpro_request(method, endpoint, **kwargs):
    """Make authenticated Simpro API request with automatic retry on auth failure"""
    max_retries = 2
    
    for attempt in range(max_retries):
        try:
            token = get_simpro_token(force_refresh=(attempt > 0))
            headers = kwargs.pop('headers', {}) if 'headers' in kwargs else {}
            headers['Authorization'] = f'Bearer {token}'
            
            url = f"{SIMPRO_BASE_URL}{endpoint}"
            response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
            
            # If we get 401, force token refresh and retry
            if response.status_code == 401 and attempt < max_retries - 1:
                print(f"[{datetime.now()}] Got 401, forcing token refresh...")
                kwargs['headers'] = {k: v for k, v in headers.items() if k != 'Authorization'}
                continue
                
            return response
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[{datetime.now()}] Request failed, retrying: {e}")
                continue
            raise
    
    return response

# ============================================
# Static File Routes
# ============================================
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

# ============================================
# API Endpoints
# ============================================
@app.route('/api/storage-locations', methods=['GET'])
@login_required
def get_storage_locations():
    """Get storage locations from JSON file"""
    try:
        with open(os.path.join(os.path.dirname(__file__), 'storage-locations.json'), 'r') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/po/<po_number>', methods=['GET'])
@login_required
def get_po_details(po_number):
    """Get PO details from Simpro"""
    try:
        # Search for PO by ID
        response = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/?ID={po_number}')
        
        if response.status_code != 200:
            return jsonify({'error': f'Simpro API error: {response.status_code}'}), 500
        
        orders = response.json()
        if not orders:
            return jsonify({'error': f'PO #{po_number} not found'}), 404
        
        po = orders[0]
        po_id = po.get('ID')
        
        # Get vendor info
        vendor_name = po.get('Vendor', {}).get('CompanyName', 'Unknown Vendor')
        
        # Get job info
        job_id = po.get('Job', {}).get('ID')
        job_number = None
        customer_name = None
        
        if job_id:
            job_response = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/?columns=ID,Name,Customer')
            if job_response.status_code == 200:
                job_data = job_response.json()
                job_number = job_data.get('ID')
                customer_name = job_data.get('Customer', {}).get('CompanyName')
        
        # Get PO line items (catalogs)
        items_response = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/')
        
        if items_response.status_code != 200:
            return jsonify({'error': 'Failed to get PO items'}), 500
        
        catalogs = items_response.json()
        
        # DEBUG: Print ALL fields in first catalog item
        if catalogs:
            print(f"DEBUG - ALL KEYS in first catalog item: {list(catalogs[0].keys())}")
            print(f"DEBUG - FULL catalog item: {json.dumps(catalogs[0], indent=2, default=str)}")
        
        items = []
        for catalog in catalogs:
            catalog_id = catalog.get('Catalog', {}).get('ID')
            part_no = catalog.get('Catalog', {}).get('PartNo', '')
            description = catalog.get('Catalog', {}).get('Name', catalog.get('Description', 'Unknown Item'))
            quantity_ordered = catalog.get('Quantity', 0)
            quantity_received = catalog.get('QuantityReceived', 0)
            
            # Determine receipt status
            if quantity_received >= quantity_ordered:
                receipt_status = 'fully_receipted'
            elif quantity_received > 0:
                receipt_status = 'partially_receipted'
            else:
                receipt_status = 'not_receipted'
            
            items.append({
                'catalogId': catalog_id,
                'partNo': part_no,
                'description': description,
                'quantityOrdered': quantity_ordered,
                'quantityReceived': quantity_received,
                'receiptStatus': receipt_status
            })
        
        return jsonify({
            'poNumber': po_number,
            'poId': po_id,
            'vendorName': vendor_name,
            'jobNumber': job_number,
            'customerName': customer_name,
            'status': po.get('Stage', 'Unknown'),
            'items': items
        })
        
    except Exception as e:
        print(f"Error getting PO: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/allocate', methods=['POST'])
@login_required
def allocate_items():
    """Allocate items to storage location in Simpro"""
    try:
        data = request.get_json()
        
        po_id = data.get('poId')
        items = data.get('items', [])
        storage_device_id = data.get('storageDeviceId')
        storage_name = data.get('storageName', 'Unknown')
        
        if not po_id or not items or not storage_device_id:
            return jsonify({'error': 'Missing required fields'}), 400
        
        results = []
        success_count = 0
        
        for item in items:
            catalog_id = item.get('catalogId')
            quantity = item.get('quantity', 1)
            
            if not catalog_id:
                results.append({'catalogId': None, 'success': False, 'error': 'Missing catalog ID'})
                continue
            
            # Set allocation via API
            allocation_url = f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/{catalog_id}/allocations/'
            
            payload = {
                'StorageDevice': int(storage_device_id),
                'Quantity': int(quantity)
            }
            
            response = simpro_request('PUT', allocation_url, json=payload)
            
            if response.status_code in (200, 201):
                results.append({
                    'catalogId': catalog_id,
                    'success': True,
                    'quantity': quantity
                })
                success_count += 1
            else:
                results.append({
                    'catalogId': catalog_id,
                    'success': False,
                    'error': f'API returned {response.status_code}'
                })
        
        # Log the allocation
        staff_id = session.get('staff_id')
        staff_name = session.get('display_name', 'Unknown')
        po_number = data.get('poNumber', po_id)
        job_number = data.get('jobNumber', '')
        vendor_name = data.get('vendorName', '')
        
        log_allocation(
            staff_id=staff_id,
            staff_name=staff_name,
            po_number=po_number,
            job_number=job_number,
            vendor_name=vendor_name,
            items_count=success_count,
            storage_location=storage_name,
            allocation_type='po_receive',
            verified=1 if success_count > 0 else 0
        )
        
        return jsonify({
            'success': success_count > 0,
            'results': results,
            'successCount': success_count,
            'totalItems': len(items),
            'allocatedBy': staff_name
        })
        
    except Exception as e:
        print(f"Allocation error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/storage/<int:storage_id>/stock', methods=['GET'])
@login_required
def get_storage_stock(storage_id):
    """Get items currently in a storage location"""
    try:
        # Query Simpro for stock in this storage device
        response = simpro_request('GET', f'/companies/{COMPANY_ID}/storageDevices/{storage_id}/stock/')
        
        if response.status_code != 200:
            return jsonify({'items': [], 'error': f'Failed to get stock: {response.status_code}'})
        
        stock_data = response.json()
        items = []
        
        # Debug: Log first item structure
        if stock_data:
            print(f"First stock item structure: {stock_data[0]}")
        
        for stock in stock_data:
            # The stock endpoint returns items with different structure
            # Try multiple ways to get the ID
            stock_id = stock.get('ID') or stock.get('StockID') or stock.get('id')
            
            # Extract item details
            item = {
                'stockId': stock_id,
                'catalogId': stock.get('Catalog', {}).get('ID') if isinstance(stock.get('Catalog'), dict) else stock.get('Catalog'),
                'partNo': stock.get('Catalog', {}).get('PartNo', stock.get('PartNo')) if isinstance(stock.get('Catalog'), dict) else stock.get('PartNo'),
                'description': stock.get('Catalog', {}).get('Name', stock.get('Name', 'Unknown Item')) if isinstance(stock.get('Catalog'), dict) else stock.get('Name', 'Unknown Item'),
                'name': stock.get('Name', ''),
                'quantity': stock.get('Quantity', 1),
                'jobId': stock.get('Job', {}).get('ID') if stock.get('Job') else None,
                'jobNumber': stock.get('Job', {}).get('Name') if stock.get('Job') else None,
                'rawData': stock  # For debugging
            }
            print(f"Processed item: stockId={item['stockId']}, catalogId={item['catalogId']}")
            items.append(item)
        
        return jsonify({
            'items': items,
            'count': len(items),
            'storageId': storage_id
        })
        
    except Exception as e:
        print(f"Error getting storage stock: {e}")
        return jsonify({'items': [], 'error': str(e)})

@app.route('/api/relocate', methods=['POST'])
@login_required
def relocate_items():
    """Relocate items from one storage location to another - queues for browser automation"""
    try:
        data = request.get_json()
        
        source_id = data.get('sourceId')
        source_name = data.get('sourceName', 'Unknown')
        dest_id = data.get('destId')
        dest_name = data.get('destName', 'Unknown')
        items = data.get('items', [])
        staff_member = session.get('username', 'unknown')
        
        if not source_id or not dest_id or not items:
            return jsonify({'error': 'Missing required fields'}), 400
        
        if source_id == dest_id:
            return jsonify({'error': 'Source and destination cannot be the same'}), 400
        
        # NOTE: Simpro API does NOT support stock transfers via API
        # The storageDevices/{id}/stock/ endpoint only allows GET/SEARCH
        # Stock transfers must be done through the Simpro web UI
        
        # Queue the relocation for browser automation processing
        conn = get_db()
        cursor = conn.cursor()
        
        # Create pending_relocations table if needed
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_relocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                source_name TEXT,
                dest_id INTEGER NOT NULL,
                dest_name TEXT,
                catalog_id INTEGER NOT NULL,
                part_no TEXT,
                description TEXT,
                quantity INTEGER NOT NULL,
                job_id INTEGER,
                staff_member TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                error_message TEXT
            )
        ''')
        
        # Queue each item for relocation
        queued_count = 0
        for item in items:
            catalog_id = item.get('catalogId')
            quantity = item.get('quantity', 1)
            part_no = item.get('partNo', '')
            description = item.get('description', '')
            job_id = item.get('jobId')
            
            print(f"Queuing relocation: catalog={catalog_id}, qty={quantity}, from {source_name} to {dest_name}")
            
            cursor.execute('''
                INSERT INTO pending_relocations 
                (source_id, source_name, dest_id, dest_name, catalog_id, part_no, description, quantity, job_id, staff_member)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (source_id, source_name, dest_id, dest_name, catalog_id, part_no, description, quantity, job_id, staff_member))
            queued_count += 1
        
        conn.commit()
        conn.close()
        
        # Return success - the actual transfer will be processed via browser automation
        return jsonify({
            'success': True,
            'message': f'Queued {queued_count} item(s) for relocation from {source_name} to {dest_name}',
            'queuedCount': queued_count,
            'requiresBrowserAutomation': True,
            'note': 'Stock transfers in Simpro require browser automation. Items have been queued and will be processed shortly.'
        })
        
    except Exception as e:
        print(f"Error queuing relocation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/pending-relocations', methods=['GET'])
@login_required
def get_pending_relocations():
    """Get list of pending relocations awaiting browser automation"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pending_relocations'")
        if not cursor.fetchone():
            conn.close()
            return jsonify({'relocations': [], 'count': 0})
        
        cursor.execute('''
            SELECT id, source_id, source_name, dest_id, dest_name, catalog_id, part_no, 
                   description, quantity, job_id, staff_member, status, created_at, processed_at, error_message
            FROM pending_relocations
            WHERE status = 'pending'
            ORDER BY created_at ASC
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        relocations = []
        for row in rows:
            relocations.append({
                'id': row[0],
                'sourceId': row[1],
                'sourceName': row[2],
                'destId': row[3],
                'destName': row[4],
                'catalogId': row[5],
                'partNo': row[6],
                'description': row[7],
                'quantity': row[8],
                'jobId': row[9],
                'staffMember': row[10],
                'status': row[11],
                'createdAt': row[12],
                'processedAt': row[13],
                'errorMessage': row[14]
            })
        
        return jsonify({'relocations': relocations, 'count': len(relocations)})
        
    except Exception as e:
        print(f"Error getting pending relocations: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pending-relocations/<int:relocation_id>/complete', methods=['POST'])
@login_required  
def complete_relocation(relocation_id):
    """Mark a relocation as completed (called after browser automation succeeds)"""
    try:
        data = request.get_json() or {}
        success = data.get('success', True)
        error_message = data.get('error', None)
        
        conn = get_db()
        cursor = conn.cursor()
        
        if success:
            cursor.execute('''
                UPDATE pending_relocations 
                SET status = 'completed', processed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (relocation_id,))
        else:
            cursor.execute('''
                UPDATE pending_relocations 
                SET status = 'failed', processed_at = CURRENT_TIMESTAMP, error_message = ?
                WHERE id = ?
            ''', (error_message, relocation_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error completing relocation: {e}")
        return jsonify({'error': str(e)}), 500

# NOTE: Simpro API does NOT support stock transfers via API (tested Feb 2026)
# The storageDevices/{id}/stock/ endpoint only allows GET/SEARCH methods
# Stock transfers must be done through the Simpro web UI via browser automation

@app.route('/api/stock-pick-list', methods=['GET'])
@login_required
def get_stock_pick_list():
    """Get items that need to be picked from stock"""
    try:
        # Get pending vendor orders
        response = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/?Stage=Pending&columns=ID,Job,Vendor')
        
        if response.status_code != 200:
            return jsonify({'items': [], 'error': 'Failed to get pending orders'})
        
        orders = response.json()
        pick_items = []
        
        # For now return a sample - full implementation would scan jobs for stock items
        for order in orders[:5]:
            job_id = order.get('Job', {}).get('ID')
            if job_id:
                pick_items.append({
                    'jobId': job_id,
                    'orderId': order.get('ID'),
                    'vendor': order.get('Vendor', {}).get('CompanyName', 'Unknown')
                })
        
        return jsonify({
            'items': pick_items,
            'count': len(pick_items)
        })
        
    except Exception as e:
        return jsonify({'items': [], 'error': str(e)})

# ============================================
# Initialize and Run
# ============================================
if __name__ == '__main__':
    print("Initializing database...")
    init_db()
    print("Starting PO Receiving App server...")
    print("Staff management enabled")
    app.run(host='0.0.0.0', port=8000, debug=False)

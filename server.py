#!/usr/bin/env python3
"""
PO Receiving App - Backend Server
With Staff Management System
"""

import os
import json
import hashlib
import time
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session
import requests
import io
import base64
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', '2ndfix-po-app-secret-key-2026-persistent')

@app.after_request
def add_cache_headers(response):
    """Prevent browser caching of HTML and JS files"""
    if response.content_type and ('text/html' in response.content_type or 
                                   'javascript' in response.content_type):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

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
            email TEXT,
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
    
    # Backorder items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS backorder_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id TEXT NOT NULL,
            po_number TEXT NOT NULL,
            catalog_id INTEGER NOT NULL,
            description TEXT,
            part_no TEXT,
            quantity_backordered INTEGER NOT NULL,
            job_number TEXT,
            customer_name TEXT,
            vendor_name TEXT,
            vendor_email TEXT,
            staff_id INTEGER,
            staff_name TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            resolved_at TEXT
        )
    ''')
    
    # Docket OCR data table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS docket_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id TEXT,
            po_number TEXT,
            supplier_name TEXT,
            packing_slip_number TEXT,
            tracking_number TEXT,
            delivery_date TEXT,
            raw_ocr_text TEXT,
            staff_id INTEGER,
            staff_name TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    
    # Fault reports table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_type TEXT NOT NULL,
            po_number TEXT,
            catalog_id TEXT,
            staff_user TEXT,
            error_code INTEGER,
            error_message TEXT,
            request_payload TEXT,
            response_body TEXT,
            endpoint TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fault_reports (
            id TEXT PRIMARY KEY,
            reporter_name TEXT NOT NULL,
            reporter_email TEXT NOT NULL,
            description TEXT NOT NULL,
            po_number TEXT,
            job_number TEXT,
            current_screen TEXT,
            error_message TEXT,
            photo_count INTEGER DEFAULT 0,
            photos_base64 TEXT,
            staff_user TEXT,
            status TEXT DEFAULT 'new',
            resolution TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            resolved_at TEXT
        )
    ''')
    
    conn.commit()
    
    # Add email column if it doesn't exist (migration for existing DBs)
    try:
        cursor.execute("ALTER TABLE staff ADD COLUMN email TEXT")
        print("Added email column to staff table")
    except:
        pass  # Column already exists
    
    # Seed all staff accounts (survives Render restarts)
    # Each staff member is created if they don't already exist
    staff_seed = [
        ('george', 'George', 'admin', '2ndFix5082', 'george@2ndfix.com.au'),
        ('jim', 'Jim', 'manager', '2ndFix5082', 'jim@2ndfix.com.au'),
        ('cherie', 'Cherie', 'manager', '2ndFix5082', None),
        ('tom', 'Tom', 'manager', '2ndFix5082', 'tom@2ndfix.com.au'),
        ('tyrese', 'Tyrese', 'staff', 'Tyrese123', None),
        ('mik', 'Mik', 'staff', '2ndFix5082$', None),
        ('ryan', 'Ryan', 'staff', '2ndFix5082$', None),
    ]
    
    for username, display_name, role, password, email in staff_seed:
        cursor.execute("SELECT COUNT(*) FROM staff WHERE username = ?", (username,))
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO staff (username, display_name, password_hash, role, active, email)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (username, display_name, hash_password(password), role, 1, email))
            print(f"Created staff account: {username} ({role})")
        elif email:
            # Update email for existing staff
            cursor.execute('UPDATE staff SET email = ? WHERE username = ? AND (email IS NULL OR email != ?)', 
                          (email, username, email))
            if cursor.rowcount > 0:
                print(f"Updated email for {username}: {email}")
    
    conn.commit()
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
    session['email'] = staff['email'] or ''
    
    return jsonify({
        'success': True,
        'staff': {
            'id': staff['id'],
            'username': staff['username'],
            'displayName': staff['display_name'],
            'role': staff['role'],
            'email': staff['email'] or ''
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
                'role': session['role'],
                'email': session.get('email', '')
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
    cursor.execute('SELECT id, username, display_name, role, email, active, created_at FROM staff ORDER BY display_name')
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
@login_required
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
# Label Image Generation
# ============================================
def _load_label_fonts():
    """Load fonts for label generation with fallbacks."""
    font_paths_regular = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/TTF/DejaVuSans.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    ]
    font_paths_bold = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
    ]
    
    regular_font = None
    bold_font = None
    regular_small = None
    
    for path in font_paths_regular:
        try:
            regular_font = ImageFont.truetype(path, 28)
            regular_small = ImageFont.truetype(path, 24)
            break
        except (OSError, IOError):
            continue
    
    for path in font_paths_bold:
        try:
            bold_font = ImageFont.truetype(path, 28)
            break
        except (OSError, IOError):
            continue
    
    if regular_font is None:
        regular_font = ImageFont.load_default()
        regular_small = regular_font
    if bold_font is None:
        bold_font = regular_font
    
    return regular_font, bold_font, regular_small

@app.route('/api/generate-labels', methods=['POST'])
@login_required
def generate_labels():
    """Generate label images as base64-encoded PNGs."""
    try:
        data = request.get_json()
        if not data or 'items' not in data:
            return jsonify({'error': 'Missing items in request'}), 400
        
        items = data['items']
        po_number = data.get('poNumber', 'N/A')
        today = datetime.now().strftime('%d/%m/%Y')
        
        regular_font, bold_font, small_font = _load_label_fonts()
        
        labels = []
        for item in items:
            # Create label image
            img = Image.new('RGB', (900, 280), 'white')
            draw = ImageDraw.Draw(img)
            
            job_number = item.get('jobNumber', '')
            customer_name = item.get('customerName', '')
            part_no = item.get('partNo', '')
            description = item.get('description', '')
            quantity = item.get('quantity', 0)
            storage_location = item.get('storageLocation', '')
            
            # Line 1: Job {jobNumber}  {customerName}  │  {partNo}  {description}
            x = 20
            y = 40
            
            # Job number and customer in regular font
            job_text = f"Job {job_number}" if job_number else ""
            if job_text:
                draw.text((x, y), job_text, fill='black', font=regular_font)
                bbox = draw.textbbox((x, y), job_text, font=regular_font)
                x = bbox[2] + 12
            
            if customer_name:
                draw.text((x, y), customer_name, fill='black', font=regular_font)
                bbox = draw.textbbox((x, y), customer_name, font=regular_font)
                x = bbox[2] + 12
            
            # Separator
            if job_text or customer_name:
                draw.text((x, y), "│", fill='black', font=regular_font)
                bbox = draw.textbbox((x, y), "│", font=regular_font)
                x = bbox[2] + 12
            
            # Part code in BOLD
            if part_no:
                draw.text((x, y), part_no, fill='black', font=bold_font)
                bbox = draw.textbbox((x, y), part_no, font=bold_font)
                x = bbox[2] + 12
            
            # Description in regular - truncate if needed
            if description:
                max_desc_width = 880 - x
                desc_text = description
                # Truncate description if too long
                while desc_text:
                    bbox = draw.textbbox((0, 0), desc_text, font=regular_font)
                    if bbox[2] - bbox[0] <= max_desc_width:
                        break
                    desc_text = desc_text[:-1]
                if desc_text != description and len(desc_text) > 3:
                    desc_text = desc_text[:-3] + '...'
                draw.text((x, y), desc_text, fill='black', font=regular_font)
            
            # Line 2: Qty: {quantity}  {storageLocation}  {date}  PO {poNumber}
            x = 20
            y = 140
            
            line2_parts = []
            line2_parts.append(f"Qty: {quantity}")
            if storage_location:
                line2_parts.append(storage_location)
            line2_parts.append(today)
            line2_parts.append(f"PO {po_number}")
            
            line2_text = "    ".join(line2_parts)
            draw.text((x, y), line2_text, fill='black', font=small_font)
            
            # Draw a thin border
            draw.rectangle([0, 0, 899, 279], outline='#cccccc', width=1)
            
            # Convert to base64 PNG
            buffer = io.BytesIO()
            img.save(buffer, format='PNG', dpi=(360, 360))
            buffer.seek(0)
            labels.append(base64.b64encode(buffer.getvalue()).decode('utf-8'))
        
        return jsonify({'labels': labels})
        
    except Exception as e:
        print(f"[{datetime.now()}] Label generation error: {e}")
        return jsonify({'error': f'Label generation failed: {str(e)}'}), 500

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
        
        po_id = orders[0].get('ID')
        
        # Get full PO record (search returns minimal data)
        full_po_response = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}')
        if full_po_response.status_code != 200:
            return jsonify({'error': 'Failed to get PO details'}), 500
        
        po = full_po_response.json()
        
        # Get vendor info from full PO record
        vendor_name = po.get('Vendor', {}).get('Name', 'Unknown Vendor')
        
        # Get job info from AssignedTo object
        assigned_to = po.get('AssignedTo', {})
        job_number = assigned_to.get('Job')
        customer_name = None
        po_reference = po.get('Reference', '')
        
        if job_number:
            job_response = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_number}/?columns=ID,Name,Customer')
            if job_response.status_code == 200:
                job_data = job_response.json()
                customer = job_data.get('Customer', {})
                # Try CompanyName first, then individual name fields
                customer_name = customer.get('CompanyName') or ''
                if not customer_name:
                    given = customer.get('GivenName', '') or ''
                    family = customer.get('FamilyName', '') or ''
                    customer_name = f"{given} {family}".strip()
                if not customer_name:
                    # Try Name field as last resort
                    customer_name = customer.get('Name', '')
        else:
            # No job assigned - this is a Stock order or merged PO
            if po_reference:
                job_number = po_reference  # e.g. "Stock" or "Job No. 5272 - Kitchen"
            else:
                job_number = 'Stock'
            # Leave customer_name empty - never use vendor/supplier name as customer
            customer_name = ''
        
        # Get PO line items (catalogs)
        items_response = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/')
        
        if items_response.status_code != 200:
            return jsonify({'error': 'Failed to get PO items'}), 500
        
        catalogs = items_response.json()
        
        # Cache for job customer lookups (avoid duplicate API calls for same job)
        job_customer_cache = {}
        
        def get_job_customer(jid):
            """Look up job number and customer name, with caching"""
            if jid in job_customer_cache:
                return job_customer_cache[jid]
            try:
                job_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/?ID={jid}&columns=ID,Name,Customer')
                if job_resp.status_code == 200:
                    jobs = job_resp.json()
                    if jobs:
                        job_data = jobs[0]
                        customer = job_data.get('Customer', {})
                        cust_name = customer.get('CompanyName') or ''
                        if not cust_name:
                            given = customer.get('GivenName', '') or ''
                            family = customer.get('FamilyName', '') or ''
                            cust_name = f"{given} {family}".strip()
                        if not cust_name:
                            cust_name = customer.get('Name', '')
                        result = {'jobNumber': str(jid), 'customerName': cust_name}
                        job_customer_cache[jid] = result
                        return result
            except Exception as je:
                print(f"Error looking up job {jid}: {je}")
            result = {'jobNumber': str(jid), 'customerName': ''}
            job_customer_cache[jid] = result
            return result
        
        items = []
        for catalog in catalogs:
            catalog_id = catalog.get('Catalog', {}).get('ID')
            part_no = catalog.get('Catalog', {}).get('PartNo', '')
            description = catalog.get('Catalog', {}).get('Name', catalog.get('Description', 'Unknown Item'))
            
            # Get quantity from allocations endpoint (quantity is not in catalog response)
            quantity_ordered = 0
            quantity_received = 0
            item_job_number = None
            item_customer_name = None
            item_storage_location = None
            
            if catalog_id:
                try:
                    alloc_response = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/{catalog_id}/allocations/')
                    if alloc_response.status_code == 200:
                        allocations = alloc_response.json()
                        for alloc in allocations:
                            qty_obj = alloc.get('Quantity', {})
                            quantity_ordered += qty_obj.get('Total', 0)
                            quantity_received += qty_obj.get('Received', 0)
                            
                            # Extract per-item job from allocation's AssignedTo
                            alloc_assigned = alloc.get('AssignedTo', {})
                            alloc_job = alloc_assigned.get('Job')
                            if alloc_job and not item_job_number:
                                job_info = get_job_customer(alloc_job)
                                item_job_number = job_info['jobNumber']
                                item_customer_name = job_info['customerName']
                            
                            # Extract current storage device
                            storage_dev = alloc.get('StorageDevice', {})
                            if isinstance(storage_dev, dict) and storage_dev.get('Name'):
                                item_storage_location = storage_dev.get('Name')
                            elif isinstance(storage_dev, dict) and storage_dev.get('ID'):
                                # Look up name from our devices list
                                sd_id = storage_dev['ID']
                                for dev in get_storage_devices():
                                    if dev['ID'] == sd_id:
                                        item_storage_location = dev['Name']
                                        break
                except Exception as e:
                    print(f"Error getting allocations for catalog {catalog_id}: {e}")
            
            # Fall back to PO-level job/customer if no per-item assignment
            if not item_job_number:
                item_job_number = str(job_number) if job_number else None
                item_customer_name = customer_name
            
            # Determine receipt status
            if quantity_ordered > 0 and quantity_received >= quantity_ordered:
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
                'receiptStatus': receipt_status,
                'jobNumber': item_job_number,
                'customerName': item_customer_name,
                'storageLocation': item_storage_location
            })
        
        return jsonify({
            'poNumber': po_number,
            'poId': po_id,
            'vendorName': vendor_name,
            'jobNumber': job_number,
            'customerName': customer_name,
            'status': po.get('Stage', 'Unknown'),
            'dueDate': po.get('DueDate'),
            'orderDate': po.get('OrderDate'),
            'items': items
        })
        
    except Exception as e:
        print(f"Error getting PO: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/allocate', methods=['POST'])
@login_required
def allocate_items():
    """Allocate items to storage location in Simpro.
    
    Handles TWO scenarios:
    1. NOT yet receipted: Uses PUT on allocations endpoint to pre-set storage device
       (stock will land directly in correct location when Ezybills receipts)
    2. ALREADY receipted: Uses Stock Transfer API to move from Stock Holding to destination
       (stock is already in Stock Holding Device 3, needs physical transfer)
    """
    try:
        data = request.get_json()
        print(f"=== ALLOCATION REQUEST ===")
        print(f"Data received: {data}")
        
        po_id = data.get('poId')
        items = data.get('items', [])
        storage_device_id = data.get('storageDeviceId')
        print(f"PO ID: {po_id}, Storage: {storage_device_id}, Items count: {len(items)}")
        print(f"Items: {items}")
        storage_name = data.get('storageName', 'Unknown')
        
        if not po_id or not items or not storage_device_id:
            return jsonify({'error': 'Missing required fields'}), 400
        
        STOCK_HOLDING_ID = 3  # Stock Holding device ID
        
        results = []
        success_count = 0
        
        # ============================================
        # Server-side receipt check (don't trust front-end status alone)
        # ============================================
        receipt_allocations = {}  # catalog_id -> {storage_device_id, storage_name, quantity}
        catalog_items_received = {}  # catalog_id -> True/False (per-catalog ItemsReceived)
        catalog_receipt_id = {}  # catalog_id -> receipt_id (for PATCH ItemsReceived)
        po_is_receipted = False
        items_received_flag = False
        
        try:
            receipts_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/receipts/')
            if receipts_resp.status_code == 200:
                receipts = receipts_resp.json()
                if receipts and len(receipts) > 0:
                    # Receipt EXISTS = PO has been financially receipted (by Ezybills or manually)
                    # Don't require ItemsReceived flag - Ezybills often doesn't tick it
                    po_is_receipted = True
                    print(f"Receipt(s) found for PO {po_id}: {len(receipts)} receipt(s)")
                    
                    # Store all receipt IDs for fallback PATCH (even if detail fails)
                    all_receipt_ids = [r.get('ID') for r in receipts if r.get('ID')]
                    first_receipt_id = all_receipt_ids[0] if all_receipt_ids else None
                    
                    for receipt in receipts:
                        receipt_id = receipt.get('ID')
                        detail_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/receipts/{receipt_id}')
                        if detail_resp.status_code == 200:
                            detail = detail_resp.json()
                            receipt_items_received = detail.get('ItemsReceived', False)
                            if receipt_items_received:
                                items_received_flag = True
                            # Map each catalog's current allocation, ItemsReceived status, and receipt ID
                            for cat in detail.get('Catalogs', []):
                                cat_id = cat.get('Catalog', {}).get('ID')
                                catalog_items_received[cat_id] = receipt_items_received
                                catalog_receipt_id[cat_id] = receipt_id
                                for alloc in cat.get('Allocations', []):
                                    sd = alloc.get('StorageDevice', {})
                                    sd_id = sd.get('ID') if isinstance(sd, dict) else sd
                                    sd_name = sd.get('Name', 'Unknown') if isinstance(sd, dict) else 'Unknown'
                                    receipt_allocations[cat_id] = {
                                        'storage_id': sd_id,
                                        'storage_name': sd_name,
                                        'quantity': alloc.get('Quantity', 0)
                                    }
                else:
                    print(f"No receipts found for PO {po_id} - truly not receipted")
            print(f"Server-side receipt check: po_is_receipted={po_is_receipted}, ItemsReceived={items_received_flag}, allocations={receipt_allocations}")
        except Exception as e:
            print(f"Receipt check error: {e}")
        
        # Separate items into categories
        pre_receipt_items = []
        post_receipt_items = []  # In Stock Holding, need transfer
        already_allocated_items = []  # Already in a non-Stock-Holding location
        
        for item in items:
            catalog_id = item.get('catalogId')
            quantity = item.get('quantity', 0)
            receipt_status = item.get('receiptStatus', 'not_receipted')
            
            if not catalog_id:
                results.append({'catalogId': None, 'success': False, 'error': 'Missing catalog ID'})
                continue
            
            # Fix quantity: if 0 or missing, use quantityOrdered from front-end, then default to 1
            if not quantity or quantity <= 0:
                qty_ordered = item.get('quantityOrdered', 0)
                if qty_ordered > 0:
                    quantity = qty_ordered
                    item['quantity'] = qty_ordered
                    print(f"Fixed quantity for catalog {catalog_id}: using quantityOrdered={qty_ordered}")
                else:
                    quantity = 1
                    item['quantity'] = 1
                    print(f"Fixed quantity for catalog {catalog_id}: defaulting to 1 (no quantityOrdered available)")
            
            # Server-side receipt detection (overrides front-end if we have data)
            is_receipted = po_is_receipted or receipt_status == 'fully_receipted'
            
            if is_receipted and catalog_id in receipt_allocations:
                current_alloc = receipt_allocations[catalog_id]
                current_storage_id = current_alloc['storage_id']
                current_storage_name = current_alloc['storage_name']
                
                if current_storage_id == int(storage_device_id):
                    # Already in the destination!
                    results.append({
                        'catalogId': catalog_id,
                        'success': True,
                        'quantity': quantity,
                        'verified': True,
                        'method': 'already_allocated',
                        'message': f'Already allocated to {current_storage_name}'
                    })
                    success_count += 1
                    already_allocated_items.append(item)
                    print(f"Catalog {catalog_id}: Already allocated to {current_storage_name} (target)")
                elif catalog_items_received.get(catalog_id, False):
                    # ItemsReceived IS ticked for this catalog - stock is "In Stock" - can use stock transfer
                    if current_storage_id != STOCK_HOLDING_ID:
                        item['source_storage_id'] = current_storage_id
                        item['source_storage_name'] = current_storage_name
                    post_receipt_items.append(item)
                    print(f"Catalog {catalog_id}: In Stock at {current_storage_name}, using stock transfer to {storage_device_id}")
                else:
                    # Receipt EXISTS but ItemsReceived NOT ticked = "In Transit"
                    # CRITICAL: Do NOT use pre-receipt PUT - it doubles cost centre entries!
                    # Instead: tick ItemsReceived on the receipt first, then stock transfer
                    r_id = catalog_receipt_id.get(catalog_id) or first_receipt_id
                    if r_id:
                        try:
                            print(f"Catalog {catalog_id}: In Transit - ticking ItemsReceived on receipt {r_id}...")
                            patch_resp = simpro_request('PATCH', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/receipts/{r_id}', json={'ItemsReceived': True})
                            print(f"ItemsReceived PATCH response: {patch_resp.status_code} - {patch_resp.text}")
                            if patch_resp.status_code in (200, 204):
                                print(f"✅ ItemsReceived set to true for receipt {r_id}")
                                # Give Simpro a moment to process and move stock into Stock Holding
                                print("Waiting 3 seconds for Simpro to process ItemsReceived...")
                                time.sleep(3)
                            else:
                                print(f"⚠️ ItemsReceived PATCH returned {patch_resp.status_code}")
                        except Exception as ir_err:
                            print(f"⚠️ Failed to set ItemsReceived: {ir_err}")
                    
                    # Now route to stock transfer (stock should be "In Stock" after ticking ItemsReceived)
                    if current_storage_id != STOCK_HOLDING_ID:
                        item['source_storage_id'] = current_storage_id
                        item['source_storage_name'] = current_storage_name
                    post_receipt_items.append(item)
                    print(f"Catalog {catalog_id}: Receipted, ItemsReceived now set, using stock transfer from {current_storage_name} to {storage_device_id}")
            elif is_receipted:
                # Receipted but no allocation data found
                # CRITICAL: NEVER use pre-receipt PUT when receipt exists - it doubles cost centre entries!
                # Always tick ItemsReceived (if needed) then stock transfer
                if not items_received_flag:
                    # Try to tick ItemsReceived - use catalog-specific receipt ID, or fall back to first receipt
                    r_id = catalog_receipt_id.get(catalog_id) or first_receipt_id
                    if r_id:
                        try:
                            print(f"Catalog {catalog_id}: No alloc data, ticking ItemsReceived on receipt {r_id}...")
                            patch_resp = simpro_request('PATCH', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/receipts/{r_id}', json={'ItemsReceived': True})
                            print(f"ItemsReceived PATCH response: {patch_resp.status_code}")
                            if patch_resp.status_code in (200, 204):
                                print(f"✅ ItemsReceived set to true for receipt {r_id}")
                                # Give Simpro a moment to process and move stock into Stock Holding
                                print("Waiting 3 seconds for Simpro to process ItemsReceived...")
                                time.sleep(3)
                        except Exception as ir_err:
                            print(f"⚠️ Failed to set ItemsReceived: {ir_err}")
                post_receipt_items.append(item)
                print(f"Catalog {catalog_id}: Receipted (no alloc data), routing to stock transfer")
            else:
                pre_receipt_items.append(item)
                print(f"Catalog {catalog_id}: Not yet receipted, using pre-receipt allocation")
        
        print(f"Pre-receipt items (allocation): {len(pre_receipt_items)}")
        print(f"Post-receipt items (stock transfer): {len(post_receipt_items)}")
        print(f"Already allocated items: {len(already_allocated_items)}")
        
        # ============================================
        # Path 1: Pre-receipt allocation (set storage before Ezybills receipts)
        # CRITICAL: Must preserve AssignedTo/CostCenter from existing allocations!
        # The PUT replaces ALL allocations, so we must include AssignedTo.
        # ============================================
        for item in pre_receipt_items:
            catalog_id = item.get('catalogId')
            quantity = item.get('quantity', 1)
            
            # Use the quantity from the request, but also validate against ordered qty
            qty_ordered = item.get('quantityOrdered', 0)
            if qty_ordered > 0 and quantity <= 0:
                quantity = qty_ordered
            
            allocation_url = f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/{catalog_id}/allocations/'
            
            # Fetch existing allocations to get quantity if needed
            try:
                existing_resp = simpro_request('GET', allocation_url)
                if existing_resp.status_code == 200:
                    existing_allocs = existing_resp.json()
                    print(f"[PRE-RECEIPT] Existing allocations for catalog {catalog_id}: {existing_allocs}")
                    if existing_allocs and len(existing_allocs) > 0:
                        # Use the existing quantity if ours seems wrong
                        if quantity <= 0:
                            for existing_alloc in existing_allocs:
                                eq = existing_alloc.get('Quantity', 0)
                                if eq > 0:
                                    quantity = eq
                                    print(f"[PRE-RECEIPT] Using existing quantity: {quantity}")
                                    break
            except Exception as ae:
                print(f"[PRE-RECEIPT] Error fetching existing allocations: {ae}")
            
            # Build payload - Simpro API requires an ARRAY of allocations
            # NOTE: Do NOT include AssignedTo - it's read-only and causes 422 errors
            # Simpro preserves existing AssignedTo/CostCenter when only StorageDevice is changed
            alloc_entry = {
                'StorageDevice': int(storage_device_id),
                'Quantity': int(quantity)
            }
            
            payload = [alloc_entry]
            
            print(f"[PRE-RECEIPT] PUT {allocation_url} with payload: {payload}")
            response = simpro_request('PUT', allocation_url, json=payload)
            print(f"API Response: {response.status_code} - {response.text}")
            
            if response.status_code in (200, 201):
                # Verify the allocation was applied
                verified = False
                try:
                    verify_resp = simpro_request('GET', allocation_url)
                    if verify_resp.status_code == 200:
                        allocs = verify_resp.json()
                        for alloc in allocs:
                            sd = alloc.get('StorageDevice', {})
                            if isinstance(sd, dict) and sd.get('ID') == int(storage_device_id):
                                verified = True
                                break
                            elif sd == int(storage_device_id):
                                verified = True
                                break
                except Exception as ve:
                    print(f"Verification error for catalog {catalog_id}: {ve}")
                
                results.append({
                    'catalogId': catalog_id,
                    'success': True,
                    'quantity': quantity,
                    'verified': verified,
                    'method': 'pre_receipt_allocation'
                })
                success_count += 1
                if not verified:
                    print(f"WARNING: Allocation for catalog {catalog_id} could not be verified!")
            else:
                error_detail = response.text[:500] if response.text else 'No response body'
                print(f"❌ PRE-RECEIPT PUT FAILED: PO {po_number}, Catalog {catalog_id}, Status {response.status_code}, Response: {error_detail}")
                
                # Log error to DB for debugging
                try:
                    import json as json_mod
                    err_conn = get_db()
                    err_cursor = err_conn.cursor()
                    err_cursor.execute('''INSERT INTO error_logs (error_type, po_number, catalog_id, staff_user, error_code, error_message, request_payload, response_body, endpoint)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        ('pre_receipt_allocation', str(po_number), str(catalog_id), staff_name, 
                         response.status_code, f'API returned {response.status_code}',
                         json_mod.dumps(payload), error_detail, allocation_url))
                    err_conn.commit()
                    err_conn.close()
                except Exception as log_err:
                    print(f"Error logging failed: {log_err}")
                
                results.append({
                    'catalogId': catalog_id,
                    'success': False,
                    'error': f'API returned {response.status_code}',
                    'detail': error_detail,
                    'method': 'pre_receipt_allocation'
                })
        
        # ============================================
        # Path 2: Post-receipt stock transfer (move from current location to destination)
        # ============================================
        if post_receipt_items:
            # Skip service/non-physical items (delivery charges, freight, etc.)
            SERVICE_PATTERNS = ['SHIP', 'DELIVERY', 'FREIGHT', 'POSTAGE', 'TRANSPORT']
            physical_items = []
            for item in post_receipt_items:
                part_no = str(item.get('partNo', '') or '').upper().strip()
                desc = str(item.get('description', '') or '').upper().strip()
                is_service = any(p in part_no or p in desc for p in SERVICE_PATTERNS)
                if is_service:
                    print(f"⏭️ Skipping service item: {part_no} - {desc}")
                    results.append({
                        'catalogId': item.get('catalogId'),
                        'success': True,
                        'quantity': item.get('quantity', 1),
                        'verified': True,
                        'method': 'skipped_service',
                        'message': f'Skipped: {desc} is a service/delivery item (not physical stock)'
                    })
                    success_count += 1
                else:
                    physical_items.append(item)
            
            post_receipt_items = physical_items
            
            # Group items by source storage device (most will be Stock Holding, but some may be elsewhere)
            by_source = {}
            for item in post_receipt_items:
                source_id = item.get('source_storage_id', STOCK_HOLDING_ID)
                source_name = item.get('source_storage_name', 'Stock Holding')
                if source_id not in by_source:
                    by_source[source_id] = {'name': source_name, 'items': []}
                by_source[source_id]['items'].append(item)
            
            for source_id, group in by_source.items():
                source_name = group['name']
                group_items = group['items']
                
                # Pre-check: Query stock levels to skip items with zero stock
                items_with_stock = []
                for item in group_items:
                    catalog_id = item.get('catalogId')
                    part_no = item.get('partNo', '')
                    desc = item.get('description', '')
                    quantity = item.get('quantity', 1)
                    
                    try:
                        # Use storageDevice stock endpoint (catalogs/stockOnHand returns 404)
                        stock_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/storageDevices/{source_id}/stock/?Catalog.ID={catalog_id}')
                        if stock_resp.status_code == 200:
                            stock_data = stock_resp.json()
                            source_stock = 0
                            if stock_data and len(stock_data) > 0:
                                source_stock = stock_data[0].get('InventoryCount', 0)
                            
                            if source_stock <= 0:
                                # Retry: Simpro may still be processing ItemsReceived
                                retried = False
                                for retry in range(3):
                                    print(f"⏳ {part_no}: 0 stock in {source_name}, retry {retry+1}/3 (waiting 3s)...")
                                    time.sleep(3)
                                    retry_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/storageDevices/{source_id}/stock/?Catalog.ID={catalog_id}')
                                    if retry_resp.status_code == 200:
                                        retry_data = retry_resp.json()
                                        if retry_data and len(retry_data) > 0:
                                            source_stock = retry_data[0].get('InventoryCount', 0)
                                            if source_stock > 0:
                                                print(f"✅ {part_no}: Stock appeared after retry {retry+1}: {source_stock}")
                                                retried = True
                                                break
                                
                                if source_stock <= 0:
                                    print(f"⏭️ Skipping {part_no} ({desc}): 0 stock in {source_name} after 3 retries")
                                    results.append({
                                        'catalogId': catalog_id,
                                        'success': False,
                                        'quantity': quantity,
                                        'method': 'skipped_zero_stock',
                                        'error': f'No stock available in {source_name} - item may not have arrived yet. ItemsReceived was ticked but stock did not appear after retries.'
                                    })
                                    continue
                            
                            print(f"📦 {part_no}: {source_stock} in {source_name}")
                            
                            # Cap quantity to available stock
                            if quantity > source_stock:
                                print(f"⚠️ Reducing {part_no} qty from {quantity} to {source_stock} (available stock)")
                                item['quantity'] = int(source_stock)
                        else:
                            # If stock check fails, skip item to avoid 404 on transfer
                            print(f"⚠️ Could not check stock for catalog {catalog_id}: {stock_resp.status_code} - skipping")
                            results.append({
                                'catalogId': catalog_id,
                                'success': False,
                                'quantity': quantity,
                                'method': 'skipped_stock_check_failed',
                                'error': f'Could not verify stock level in {source_name} (API returned {stock_resp.status_code})'
                            })
                            continue
                    except Exception as e:
                        print(f"⚠️ Stock check error for catalog {catalog_id}: {e} - skipping")
                        results.append({
                            'catalogId': catalog_id,
                            'success': False,
                            'quantity': quantity,
                            'method': 'skipped_stock_check_error',
                            'error': f'Stock check failed: {str(e)}'
                        })
                        continue
                    
                    items_with_stock.append(item)
                
                if not items_with_stock:
                    print(f"No items with stock to transfer from {source_name}")
                    continue
                
                group_items = items_with_stock
                
                transfer_items = []
                for item in group_items:
                    catalog_id = item.get('catalogId')
                    quantity = item.get('quantity', 1)
                    if quantity <= 0:
                        quantity = 1
                    transfer_items.append({
                        'CatalogID': int(catalog_id),
                        'DestinationStorageDeviceID': int(storage_device_id),
                        'Quantity': int(quantity)
                    })
                
                transfer_payload = {
                    'SourceStorageDeviceID': int(source_id),
                    'Items': transfer_items
                }
                
                print(f"[POST-RECEIPT] Stock Transfer from {source_name} (ID:{source_id}) to {storage_name}")
                print(f"Transfer payload: {json.dumps(transfer_payload)}")
                
                transfer_response = simpro_request('POST', f'/companies/{COMPANY_ID}/stockTransfer/', json=transfer_payload)
                print(f"Stock Transfer Response: {transfer_response.status_code} - {transfer_response.text}")
                
                if transfer_response.status_code in (200, 201, 204):
                    for item in group_items:
                        results.append({
                            'catalogId': item.get('catalogId'),
                            'success': True,
                            'quantity': item.get('quantity', 1),
                            'verified': True,
                            'method': 'stock_transfer',
                            'message': f'Transferred from {source_name} to {storage_name}'
                        })
                        success_count += 1
                    print(f"✅ Stock transfer successful: {len(group_items)} items moved from {source_name} to {storage_name}")
                else:
                    error_msg = f'Stock Transfer API returned {transfer_response.status_code}'
                    try:
                        error_detail = transfer_response.json()
                        if isinstance(error_detail, dict) and 'Message' in error_detail:
                            error_msg = error_detail['Message']
                    except:
                        pass
                    
                    print(f"❌ Stock transfer failed: {error_msg}")
                    
                    # If batch transfer failed, try items individually
                    print(f"Retrying items individually...")
                    for item in group_items:
                        catalog_id = item.get('catalogId')
                        quantity = item.get('quantity', 1)
                        if quantity <= 0:
                            quantity = 1
                        
                        single_payload = {
                            'SourceStorageDeviceID': int(source_id),
                            'Items': [{
                                'CatalogID': int(catalog_id),
                                'DestinationStorageDeviceID': int(storage_device_id),
                                'Quantity': int(quantity)
                            }]
                        }
                        
                        single_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/stockTransfer/', json=single_payload)
                        if single_resp.status_code in (200, 201, 204):
                            results.append({
                                'catalogId': catalog_id,
                                'success': True,
                                'quantity': quantity,
                                'verified': True,
                                'method': 'stock_transfer',
                                'message': f'Transferred from {source_name} to {storage_name}'
                            })
                            success_count += 1
                            print(f"✅ Individual transfer success: catalog {catalog_id}")
                        else:
                            results.append({
                                'catalogId': catalog_id,
                                'success': False,
                                'error': f'Stock transfer from {source_name} failed: {single_resp.status_code}',
                                'method': 'stock_transfer'
                            })
                            print(f"❌ Individual transfer failed: catalog {catalog_id} - {single_resp.status_code}")
        
        # Log the allocation
        staff_id = session.get('staff_id')
        staff_name = session.get('display_name', 'Unknown')
        po_number = data.get('poNumber', po_id)
        job_number = data.get('jobNumber', '')
        vendor_name = data.get('vendorName', '')
        
        all_verified = all(r.get('verified', False) for r in results if r.get('success'))
        
        # ============================================
        # Set "Goods Received" status (Status ID 239)
        # This marks the PO as physically received BEFORE financial receipting
        # Only set if at least one item was successfully allocated AND there are pre-receipt items
        # ============================================
        goods_received_set = False
        if success_count > 0 and pre_receipt_items:
            try:
                print(f"=== SETTING GOODS RECEIVED STATUS for PO {po_id} ===")
                gr_response = simpro_request('PATCH', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}', json={'Status': 239})
                print(f"Goods Received API Response: {gr_response.status_code}")
                if gr_response.status_code == 204:
                    goods_received_set = True
                    print(f"✅ Goods Received status set successfully for PO {po_id}")
                else:
                    print(f"⚠️ Goods Received status update returned: {gr_response.status_code} - {gr_response.text}")
            except Exception as gr_err:
                print(f"⚠️ Failed to set Goods Received status: {gr_err}")
        
        # Determine allocation type for logging
        if post_receipt_items and pre_receipt_items:
            alloc_type = 'po_receive_mixed'
        elif post_receipt_items:
            alloc_type = 'po_receive_transfer'
        else:
            alloc_type = 'po_receive'
        
        log_allocation(
            staff_id=staff_id,
            staff_name=staff_name,
            po_number=po_number,
            job_number=job_number,
            vendor_name=vendor_name,
            items_count=success_count,
            storage_location=storage_name,
            allocation_type=alloc_type,
            verified=1 if all_verified and success_count > 0 else 0
        )
        
        print(f"=== ALLOCATION COMPLETE ===")
        print(f"Success count: {success_count}, Results: {results}, Goods Received: {goods_received_set}")
        
        # Build error summary for failed items
        error_summary = None
        if success_count == 0 and results:
            failed_errors = [r.get('error', 'Unknown') for r in results if not r.get('success')]
            if failed_errors:
                error_summary = '; '.join(set(failed_errors))
        
        return jsonify({
            'success': success_count > 0,
            'results': results,
            'successCount': success_count,
            'totalItems': len(items),
            'allocatedBy': staff_name,
            'allVerified': all_verified if success_count > 0 else False,
            'goodsReceivedSet': goods_received_set,
            'preReceiptCount': len(pre_receipt_items),
            'stockTransferCount': len(post_receipt_items),
            'error': error_summary
        })
        
    except Exception as e:
        print(f"Allocation error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/error-logs', methods=['GET'])
@login_required
def get_error_logs():
    """Get recent allocation error logs"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM error_logs ORDER BY created_at DESC LIMIT 50')
        columns = [desc[0] for desc in cursor.description]
        logs = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return jsonify({'count': len(logs), 'logs': logs})
    except Exception as e:
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
    """Relocate items from one storage location to another using Simpro Stock Transfer API"""
    try:
        data = request.get_json()
        
        source_id = data.get('sourceId')
        source_name = data.get('sourceName', 'Unknown')
        dest_id = data.get('destId')
        dest_name = data.get('destName', 'Unknown')
        items = data.get('items', [])
        staff_member = session.get('username', 'unknown')
        staff_name = session.get('display_name', staff_member)
        
        if not source_id or not dest_id or not items:
            return jsonify({'error': 'Missing required fields'}), 400
        
        if source_id == dest_id:
            return jsonify({'error': 'Source and destination cannot be the same'}), 400
        
        # Build Stock Transfer API payload
        transfer_items = []
        for item in items:
            catalog_id = item.get('catalogId')
            quantity = item.get('quantity', 1)
            if catalog_id:
                transfer_items.append({
                    'CatalogID': int(catalog_id),
                    'DestinationStorageDeviceID': int(dest_id),
                    'Quantity': int(quantity)
                })
        
        if not transfer_items:
            return jsonify({'error': 'No valid items to transfer'}), 400
        
        payload = {
            'SourceStorageDeviceID': int(source_id),
            'Items': transfer_items
        }
        
        print(f"=== STOCK TRANSFER REQUEST ===")
        print(f"From: {source_name} (ID: {source_id}) -> To: {dest_name} (ID: {dest_id})")
        print(f"Items: {len(transfer_items)}")
        print(f"Payload: {json.dumps(payload)}")
        
        # Execute stock transfer via Simpro API
        response = simpro_request('POST', f'/companies/{COMPANY_ID}/stockTransfer/', json=payload)
        print(f"Stock Transfer API Response: {response.status_code} - {response.text}")
        
        if response.status_code in (200, 201, 204):
            # Log the transfer
            staff_id = session.get('staff_id')
            log_allocation(
                staff_id=staff_id,
                staff_name=staff_name,
                po_number='',
                job_number='',
                vendor_name='',
                items_count=len(transfer_items),
                storage_location=f'{source_name} → {dest_name}',
                allocation_type='stock_transfer',
                verified=1
            )
            
            print(f"=== STOCK TRANSFER COMPLETE ===")
            print(f"Transferred {len(transfer_items)} item(s) from {source_name} to {dest_name}")
            
            return jsonify({
                'success': True,
                'message': f'Successfully transferred {len(transfer_items)} item(s) from {source_name} to {dest_name}',
                'transferredCount': len(transfer_items),
                'transferredBy': staff_name
            })
        else:
            error_msg = f'Simpro API returned {response.status_code}'
            try:
                error_detail = response.json()
                if isinstance(error_detail, dict) and 'Message' in error_detail:
                    error_msg = error_detail['Message']
            except:
                error_msg = response.text or error_msg
            
            print(f"=== STOCK TRANSFER FAILED ===")
            print(f"Error: {error_msg}")
            
            return jsonify({
                'success': False,
                'error': error_msg
            }), 400
        
    except Exception as e:
        print(f"Error executing stock transfer: {e}")
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
# Photo Upload Endpoint
# ============================================
@app.route('/api/upload-photos', methods=['POST'])
@login_required
def upload_photos():
    """Upload delivery photos to Simpro job AND PO attachments"""
    try:
        data = request.get_json()
        po_number = data.get('poNumber', 'Unknown')
        po_simpro_id = data.get('poSimproId')  # Internal Simpro PO ID for attachment
        job_ids = data.get('jobIds', [])
        photos = data.get('photos', [])
        
        if not photos or (not job_ids and not po_simpro_id):
            return jsonify({'success': False, 'error': 'No photos or destinations provided'})
        
        results = []
        po_results = []
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        # ---- PART 1: Upload to Job attachments ----
        for job_id in job_ids:
            if not job_id or str(job_id) == 'N/A':
                continue
                
            # Step 1: Get existing folders to check for "Materials Received"
            folder_id = None
            try:
                folders_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/attachments/folders/')
                if folders_resp.status_code == 200:
                    folders = folders_resp.json()
                    for folder in folders:
                        if folder.get('Name', '').strip().lower() == 'materials received':
                            folder_id = folder.get('ID')
                            break
            except Exception as fe:
                print(f"Error checking folders for job {job_id}: {fe}")
            
            # Step 2: Create folder if not exists
            if not folder_id:
                try:
                    create_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/jobs/{job_id}/attachments/folders/',
                                                 json={"Name": "Materials Received"})
                    if create_resp.status_code in (200, 201):
                        folder_data = create_resp.json()
                        folder_id = folder_data.get('ID')
                        print(f"Created 'Materials Received' folder (ID: {folder_id}) for job {job_id}")
                    else:
                        print(f"Failed to create folder for job {job_id}: {create_resp.status_code} {create_resp.text}")
                except Exception as cfe:
                    print(f"Error creating folder for job {job_id}: {cfe}")
            
            # Step 3: Upload each photo to job
            for photo in photos:
                base64_data = photo.get('base64', '')
                filename = photo.get('filename', f'PO_{po_number}_{date_str}.jpg')
                
                if ',' in base64_data:
                    base64_data = base64_data.split(',')[1]
                
                upload_payload = {
                    "Filename": filename,
                    "Public": True,
                    "Base64Data": base64_data
                }
                
                if folder_id:
                    upload_payload["Folder"] = folder_id
                
                try:
                    upload_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/jobs/{job_id}/attachments/files/',
                                                 json=upload_payload)
                    if upload_resp.status_code in (200, 201):
                        results.append({'target': f'Job {job_id}', 'filename': filename, 'success': True})
                        print(f"Uploaded {filename} to job {job_id}")
                    else:
                        results.append({'target': f'Job {job_id}', 'filename': filename, 'success': False, 'error': f'Status {upload_resp.status_code}'})
                        print(f"Failed upload {filename} to job {job_id}: {upload_resp.status_code} {upload_resp.text}")
                except Exception as ue:
                    results.append({'target': f'Job {job_id}', 'filename': filename, 'success': False, 'error': str(ue)})
        
        # ---- PART 2: Upload to PO attachments ----
        if po_simpro_id:
            # Get or create "Delivery Photos" folder on PO
            po_folder_id = None
            try:
                po_folders_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_simpro_id}/attachments/folders/')
                if po_folders_resp.status_code == 200:
                    po_folders = po_folders_resp.json()
                    for folder in po_folders:
                        if folder.get('Name', '').strip().lower() == 'delivery photos':
                            po_folder_id = folder.get('ID')
                            break
            except Exception as fe:
                print(f"Error checking PO folders for PO {po_simpro_id}: {fe}")
            
            if not po_folder_id:
                try:
                    create_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/vendorOrders/{po_simpro_id}/attachments/folders/',
                                                 json={"Name": "Delivery Photos"})
                    if create_resp.status_code in (200, 201):
                        po_folder_data = create_resp.json()
                        po_folder_id = po_folder_data.get('ID')
                        print(f"Created 'Delivery Photos' folder (ID: {po_folder_id}) for PO {po_simpro_id}")
                except Exception as cfe:
                    print(f"Error creating PO folder for PO {po_simpro_id}: {cfe}")
            
            # Upload each photo to PO
            print(f"PO upload: po_simpro_id={po_simpro_id}, po_folder_id={po_folder_id}, photos count={len(photos)}")
            for photo in photos:
                base64_data = photo.get('base64', '')
                filename = photo.get('filename', f'PO_{po_number}_{date_str}.jpg')
                
                if ',' in base64_data:
                    base64_data = base64_data.split(',')[1]
                
                print(f"PO upload attempt: filename={filename}, base64 length={len(base64_data)}")
                
                po_upload_payload = {
                    "Filename": filename,
                    "Public": True,
                    "Base64Data": base64_data
                }
                
                if po_folder_id:
                    po_upload_payload["Folder"] = int(po_folder_id) if po_folder_id else None
                
                try:
                    po_upload_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/vendorOrders/{po_simpro_id}/attachments/files/',
                                                     json=po_upload_payload)
                    print(f"PO upload response: {po_upload_resp.status_code} {po_upload_resp.text[:500]}")
                    if po_upload_resp.status_code in (200, 201, 202):
                        results.append({'target': f'PO {po_number}', 'filename': filename, 'success': True})
                        po_results.append(True)
                        print(f"Uploaded {filename} to PO {po_simpro_id}")
                    else:
                        # Retry without folder in case folder ID is the issue
                        print(f"PO upload failed with folder, retrying without folder...")
                        retry_payload = {
                            "Filename": filename,
                            "Public": True,
                            "Base64Data": base64_data
                        }
                        retry_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/vendorOrders/{po_simpro_id}/attachments/files/',
                                                     json=retry_payload)
                        print(f"PO retry response: {retry_resp.status_code} {retry_resp.text[:500]}")
                        if retry_resp.status_code in (200, 201, 202):
                            results.append({'target': f'PO {po_number}', 'filename': filename, 'success': True})
                            po_results.append(True)
                            print(f"Uploaded {filename} to PO {po_simpro_id} (without folder)")
                        else:
                            results.append({'target': f'PO {po_number}', 'filename': filename, 'success': False, 'error': f'Status {retry_resp.status_code}: {retry_resp.text[:200]}'})
                            po_results.append(False)
                except Exception as ue:
                    print(f"PO upload exception: {ue}")
                    results.append({'target': f'PO {po_number}', 'filename': filename, 'success': False, 'error': str(ue)})
                    po_results.append(False)
        
        success_count = sum(1 for r in results if r.get('success'))
        job_uploads = sum(1 for r in results if r.get('success') and r.get('target', '').startswith('Job'))
        po_uploads = sum(1 for r in results if r.get('success') and r.get('target', '').startswith('PO'))
        
        return jsonify({
            'success': success_count > 0,
            'uploaded': success_count,
            'jobUploads': job_uploads,
            'poUploads': po_uploads,
            'total': len(results),
            'results': results
        })
        
    except Exception as e:
        print(f"Photo upload error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# Backorder Endpoints
# ============================================
@app.route('/api/backorder', methods=['POST'])
@login_required
def save_backorder_items():
    """Save backorder items"""
    try:
        data = request.get_json()
        items = data.get('items', [])
        po_id = data.get('poId', '')
        po_number = data.get('poNumber', '')
        vendor_name = data.get('vendorName', '')
        staff_id = session.get('staff_id')
        staff_name = session.get('display_name', 'Unknown')
        
        conn = get_db()
        cursor = conn.cursor()
        
        saved_count = 0
        for item in items:
            cursor.execute('''
                INSERT INTO backorder_items 
                (po_id, po_number, catalog_id, description, part_no, quantity_backordered, 
                 job_number, customer_name, vendor_name, staff_id, staff_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                po_id, po_number, item.get('catalogId'),
                item.get('description', ''), item.get('partNo', ''),
                item.get('quantity', 0), item.get('jobNumber', ''),
                item.get('customerName', ''), vendor_name,
                staff_id, staff_name
            ))
            saved_count += 1
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'savedCount': saved_count})
    except Exception as e:
        print(f"Backorder save error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/backorder', methods=['GET'])
@login_required
def get_backorder_items():
    """Get backorder items"""
    try:
        status = request.args.get('status', 'pending')
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM backorder_items 
            WHERE status = ?
            ORDER BY created_at DESC
        ''', (status,))
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({'items': items, 'count': len(items)})
    except Exception as e:
        print(f"Backorder list error: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================
# Docket Data Endpoints
# ============================================
@app.route('/api/docket-data', methods=['POST'])
@login_required
def save_docket_data():
    """Save OCR extraction results from docket photo"""
    try:
        data = request.get_json()
        staff_id = session.get('staff_id')
        staff_name = session.get('display_name', 'Unknown')
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO docket_data 
            (po_id, po_number, supplier_name, packing_slip_number, 
             tracking_number, delivery_date, raw_ocr_text, staff_id, staff_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('poId', ''), data.get('poNumber', ''),
            data.get('supplierName', ''), data.get('packingSlipNumber', ''),
            data.get('trackingNumber', ''), data.get('deliveryDate', ''),
            data.get('rawOcrText', ''), staff_id, staff_name
        ))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Docket data save error: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================
# Picking Slip Endpoint
# ============================================
@app.route('/api/picking-slip/generate', methods=['POST'])
@login_required
def generate_picking_slip():
    """Generate a picking slip PDF and upload it to the job in Simpro"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        data = request.get_json()
        po_number = data.get('poNumber', 'Unknown')
        job_number = data.get('jobNumber', 'Unknown')
        vendor_name = data.get('vendorName', 'Unknown')
        customer_name = data.get('customerName', 'Unknown')
        items = data.get('items', [])

        if not items:
            return jsonify({'success': False, 'error': 'No items provided'}), 400

        # Generate PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                leftMargin=15*mm, rightMargin=15*mm,
                                topMargin=15*mm, bottomMargin=15*mm)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=22, spaceAfter=6)
        company_style = ParagraphStyle('Company', parent=styles['Normal'], fontSize=12, spaceAfter=12, textColor=colors.grey)
        info_style = ParagraphStyle('Info', parent=styles['Normal'], fontSize=11, spaceAfter=3)
        cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=10, leading=13)
        footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey)

        date_str = datetime.now().strftime('%Y-%m-%d')
        date_display = datetime.now().strftime('%d %b %Y  %I:%M %p')

        elements = []

        # Header
        elements.append(Paragraph("PICKING SLIP", title_style))
        elements.append(Paragraph("2nd Fix Hardware Pty Ltd", company_style))

        # Info block
        elements.append(Paragraph(f"<b>Job Number:</b> {job_number} &nbsp;&nbsp;&nbsp; <b>Customer:</b> {customer_name}", info_style))
        elements.append(Paragraph(f"<b>PO Number:</b> {po_number} &nbsp;&nbsp;&nbsp; <b>Vendor:</b> {vendor_name}", info_style))
        elements.append(Paragraph(f"<b>Date:</b> {date_display}", info_style))
        elements.append(Spacer(1, 10*mm))

        # Table
        table_data = [['#', 'Part No', 'Description', 'Qty', 'Storage Location']]
        for idx, item in enumerate(items, 1):
            table_data.append([
                str(idx),
                Paragraph(str(item.get('partNo', '')), cell_style),
                Paragraph(str(item.get('description', '')), cell_style),
                str(item.get('quantity', '')),
                str(item.get('storageLocation', ''))
            ])

        col_widths = [25, 80, 200, 35, 100]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#333333')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (3, 0), (3, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)

        elements.append(Spacer(1, 15*mm))
        elements.append(Paragraph("Generated by PO Receiving App", footer_style))

        doc.build(elements)

        # Get PDF bytes and base64 encode
        pdf_bytes = buffer.getvalue()
        buffer.close()
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        # Upload to Simpro job attachments
        job_id = job_number
        filename = f"Picking_Slip_PO_{po_number}_{date_str}.pdf"

        # Get or create "Materials Received" folder
        folder_id = None
        try:
            folders_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/attachments/folders/')
            if folders_resp.status_code == 200:
                folders = folders_resp.json()
                for folder in folders:
                    if folder.get('Name', '').strip().lower() == 'materials received':
                        folder_id = folder.get('ID')
                        break
        except Exception as fe:
            print(f"Error checking folders for job {job_id}: {fe}")

        if not folder_id:
            try:
                create_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/jobs/{job_id}/attachments/folders/',
                                             json={"Name": "Materials Received"})
                if create_resp.status_code in (200, 201):
                    folder_data = create_resp.json()
                    folder_id = folder_data.get('ID')
                    print(f"Created 'Materials Received' folder (ID: {folder_id}) for job {job_id}")
                else:
                    print(f"Failed to create folder for job {job_id}: {create_resp.status_code} {create_resp.text}")
            except Exception as cfe:
                print(f"Error creating folder for job {job_id}: {cfe}")

        # Upload the PDF
        upload_payload = {
            "Filename": filename,
            "Public": True,
            "Base64Data": pdf_base64
        }
        if folder_id:
            upload_payload["Folder"] = folder_id

        upload_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/jobs/{job_id}/attachments/files/',
                                     json=upload_payload)

        if upload_resp.status_code in (200, 201):
            print(f"Uploaded picking slip {filename} to job {job_id}")
            return jsonify({
                'success': True,
                'filename': filename,
                'jobNumber': job_number,
                'message': f'Picking slip uploaded to Job {job_number}'
            })
        else:
            error_msg = f"Upload failed: {upload_resp.status_code} {upload_resp.text}"
            print(f"Failed to upload picking slip: {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), 500

    except Exception as e:
        print(f"Picking slip generation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# Needs Receipting Dashboard
# ============================================
@app.route('/api/needs-receipting')
@login_required
def needs_receipting():
    """Get allocations that may need receipting"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT po_number, job_number, vendor_name, storage_location,
               MIN(created_at) as allocated_date, SUM(items_allocated) as total_items,
               staff_name
        FROM allocation_logs 
        WHERE allocation_type = 'po_receive'
        AND created_at >= datetime('now', '-30 days')
        GROUP BY po_number
        ORDER BY created_at DESC
    ''')
    items = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'items': items, 'count': len(items)})

# ============================================
# Mystery Box Search
# ============================================
@app.route('/api/search-mystery-box')
@login_required
def search_mystery_box():
    """Search by packing slip or shipping number to identify mystery boxes"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Search query required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.*, a.storage_location, a.job_number as receipt_job
        FROM docket_data d
        LEFT JOIN allocation_logs a ON d.po_number = a.po_number AND a.allocation_type = 'po_receive'
        WHERE d.packing_slip_number LIKE ? 
        OR d.tracking_number LIKE ?
        OR d.po_number LIKE ?
        OR d.supplier_name LIKE ?
        ORDER BY d.created_at DESC
        LIMIT 20
    ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'results': results, 'count': len(results)})

# ============================================
# Fault Report Endpoints
# ============================================
FAULT_WEBHOOK_URL = os.environ.get('FAULT_WEBHOOK_URL', 'https://webhooks.tasklet.ai/v1/public/webhook?token=53c558477df26839f9518bab90f10e0c')

@app.route('/api/report-fault', methods=['POST'])
@login_required
def report_fault():
    """Receive fault report from app user and forward to Tasklet webhook"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        reporter_name = data.get('reporter_name', '').strip()
        reporter_email = data.get('reporter_email', '').strip()
        description = data.get('description', '').strip()
        
        if not reporter_name or not reporter_email or not description:
            return jsonify({'error': 'Name, email, and description are required'}), 400
        
        # Auto-captured context
        po_number = data.get('po_number', '')
        job_number = data.get('job_number', '')
        current_screen = data.get('current_screen', '')
        error_message = data.get('error_message', '')
        photos_base64 = data.get('photos', [])  # List of base64-encoded images
        
        # Generate unique report ID
        report_id = str(uuid.uuid4())[:8]
        
        # Get staff username from session
        staff_user = session.get('username', 'unknown')
        
        # Store in database
        db = get_db()
        db.execute('''
            INSERT INTO fault_reports (id, reporter_name, reporter_email, description,
                po_number, job_number, current_screen, error_message,
                photo_count, photos_base64, staff_user, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
        ''', (report_id, reporter_name, reporter_email, description,
              po_number, job_number, current_screen, error_message,
              len(photos_base64), json.dumps(photos_base64), staff_user))
        db.commit()
        
        print(f"=== FAULT REPORT {report_id} ===")
        print(f"Reporter: {reporter_name} ({reporter_email})")
        print(f"Description: {description}")
        print(f"PO: {po_number}, Job: {job_number}")
        print(f"Screen: {current_screen}")
        print(f"Error: {error_message}")
        print(f"Photos: {len(photos_base64)}")
        
        # Forward to Tasklet webhook
        if FAULT_WEBHOOK_URL:
            try:
                webhook_payload = {
                    'report_id': report_id,
                    'reporter_name': reporter_name,
                    'reporter_email': reporter_email,
                    'description': description,
                    'po_number': po_number,
                    'job_number': job_number,
                    'current_screen': current_screen,
                    'error_message': error_message,
                    'photo_count': len(photos_base64),
                    'staff_user': staff_user,
                    'timestamp': datetime.now().isoformat()
                }
                # Don't include photos in webhook (too large) - Tasklet fetches them via API
                resp = requests.post(FAULT_WEBHOOK_URL, json=webhook_payload, timeout=10)
                print(f"Webhook sent: {resp.status_code}")
            except Exception as e:
                print(f"Webhook failed (report still saved): {e}")
        else:
            print("WARNING: FAULT_WEBHOOK_URL not set - report saved but not forwarded")
        
        return jsonify({
            'success': True,
            'report_id': report_id,
            'message': 'Issue reported! We\'ll investigate and email you when it\'s resolved.'
        })
        
    except Exception as e:
        print(f"Error saving fault report: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/fault-reports', methods=['GET'])
def list_fault_reports():
    """List fault reports, optionally filtered by status"""
    try:
        status = request.args.get('status', None)
        db = get_db()
        if status:
            reports = db.execute('SELECT id, reporter_name, reporter_email, description, po_number, job_number, current_screen, error_message, photo_count, staff_user, status, created_at, resolved_at FROM fault_reports WHERE status = ? ORDER BY created_at DESC', (status,)).fetchall()
        else:
            reports = db.execute('SELECT id, reporter_name, reporter_email, description, po_number, job_number, current_screen, error_message, photo_count, staff_user, status, created_at, resolved_at FROM fault_reports ORDER BY created_at DESC').fetchall()
        return jsonify({'reports': [dict(r) for r in reports], 'count': len(reports)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/fault-reports/<report_id>', methods=['GET'])
def get_fault_report(report_id):
    """Fetch a fault report by ID (for Tasklet investigation)"""
    try:
        db = get_db()
        report = db.execute('SELECT * FROM fault_reports WHERE id = ?', (report_id,)).fetchone()
        if not report:
            return jsonify({'error': 'Report not found'}), 404
        
        result = dict(report)
        # Parse photos back from JSON
        if result.get('photos_base64'):
            result['photos'] = json.loads(result['photos_base64'])
        else:
            result['photos'] = []
        del result['photos_base64']
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/fault-reports/<report_id>/resolve', methods=['POST'])
def resolve_fault_report(report_id):
    """Mark a fault report as resolved"""
    try:
        data = request.get_json() or {}
        resolution = data.get('resolution', '')
        
        db = get_db()
        db.execute('''
            UPDATE fault_reports SET status = 'resolved', resolution = ?,
                resolved_at = datetime('now') WHERE id = ?
        ''', (resolution, report_id))
        db.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# Initialize and Run
# ============================================
# Initialize database on module load (for gunicorn)
print("Initializing database...")
init_db()

if __name__ == '__main__':
    print("Starting PO Receiving App server...")
    print("Staff management enabled")
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)

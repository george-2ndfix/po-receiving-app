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

DATABASE_URL = os.environ.get('DATABASE_URL')
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session, send_file
import requests
import io
import base64
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', '2ndfix-po-app-secret-key-2026-persistent')
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True

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

# Storage devices cache (for stock_part_search)
_storage_devices_cache = None
_storage_devices_cache_time = 0

# ============================================
# Database Setup
# ============================================
class DictRow(dict):
    """Dict that also supports integer index access like sqlite3.Row"""
    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._values = list(values)
    
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

class PgCursorWrapper:
    """Wraps a psycopg2 cursor to auto-convert ? to %s and return dict rows"""
    def __init__(self, cursor):
        self._cursor = cursor
    
    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        if params:
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)
        return self._cursor
    
    def fetchone(self):
        if not self._cursor.description:
            return None
        cols = [desc[0] for desc in self._cursor.description]
        row = self._cursor.fetchone()
        if row is None:
            return None
        return DictRow(cols, row)
    
    def fetchall(self):
        if not self._cursor.description:
            return []
        cols = [desc[0] for desc in self._cursor.description]
        return [DictRow(cols, row) for row in self._cursor.fetchall()]
    
    @property
    def lastrowid(self):
        return self._cursor.fetchone()[0] if self._cursor.description else None
    
    @property
    def rowcount(self):
        return self._cursor.rowcount
    
    @property
    def description(self):
        return self._cursor.description

class PgConnectionWrapper:
    """Wraps a psycopg2 connection to return wrapped cursors"""
    def __init__(self, conn):
        self._conn = conn
    
    def cursor(self):
        return PgCursorWrapper(self._conn.cursor())
    
    def execute(self, sql, params=None):
        """Allow connection-level execute like SQLite"""
        cur = self.cursor()
        cur.execute(sql, params)
        return cur
    
    def commit(self):
        self._conn.commit()
    
    def rollback(self):
        self._conn.rollback()
    
    def close(self):
        self._conn.close()

def get_db():
    """Get database connection - PostgreSQL if DATABASE_URL is set, else SQLite"""
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL)
        return PgConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    """Initialize database tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    if USE_PG:
        # PostgreSQL DDL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS staff (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'staff' CHECK(role IN ('admin', 'manager', 'staff')),
                email TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS allocation_logs (
                id SERIAL PRIMARY KEY,
                staff_id INTEGER NOT NULL REFERENCES staff(id),
                staff_name TEXT NOT NULL,
                po_number TEXT,
                job_number TEXT,
                vendor_name TEXT,
                items_allocated INTEGER,
                storage_location TEXT,
                allocation_type TEXT,
                verified INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backorder_items (
                id SERIAL PRIMARY KEY,
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
                created_at TIMESTAMP DEFAULT NOW(),
                resolved_at TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS docket_data (
                id SERIAL PRIMARY KEY,
                po_id TEXT,
                po_number TEXT,
                supplier_name TEXT,
                packing_slip_number TEXT,
                tracking_number TEXT,
                delivery_date TEXT,
                raw_ocr_text TEXT,
                staff_id INTEGER,
                staff_name TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_logs (
                id SERIAL PRIMARY KEY,
                error_type TEXT NOT NULL,
                po_number TEXT,
                catalog_id TEXT,
                staff_user TEXT,
                error_code INTEGER,
                error_message TEXT,
                request_payload TEXT,
                response_body TEXT,
                endpoint TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
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
                created_at TIMESTAMP DEFAULT NOW(),
                resolved_at TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS damage_reports (
                id TEXT PRIMARY KEY,
                po_number TEXT,
                po_id TEXT,
                catalog_id TEXT,
                item_description TEXT,
                part_number TEXT,
                quantity_damaged INTEGER DEFAULT 1,
                notes TEXT,
                photo_count INTEGER DEFAULT 0,
                photos_base64 TEXT,
                vendor_name TEXT,
                vendor_id TEXT,
                job_number TEXT,
                customer_name TEXT,
                staff_user TEXT,
                staff_name TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT NOW(),
                resolved_at TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS damage_reports (
                id TEXT PRIMARY KEY, po_number TEXT, po_id TEXT, catalog_id TEXT,
                item_description TEXT, part_number TEXT,
                quantity_damaged INTEGER DEFAULT 1, notes TEXT,
                photo_count INTEGER DEFAULT 0, photos_base64 TEXT,
                vendor_name TEXT, vendor_id TEXT,
                job_number TEXT, customer_name TEXT,
                staff_user TEXT, staff_name TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT NOW(), resolved_at TIMESTAMP
            )
        """)
        
        conn.commit()
    else:
        # SQLite DDL
        cursor.execute("""
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
        """)
        
        cursor.execute("""
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
        """)
        
        cursor.execute("""
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
        """)
        
        cursor.execute("""
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
        """)
        
        cursor.execute("""
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
        """)
        
        cursor.execute("""
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
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS damage_reports (
                id TEXT PRIMARY KEY,
                po_number TEXT,
                po_id TEXT,
                catalog_id TEXT,
                item_description TEXT,
                part_number TEXT,
                quantity_damaged INTEGER DEFAULT 1,
                notes TEXT,
                photo_count INTEGER DEFAULT 0,
                photos_base64 TEXT,
                vendor_name TEXT,
                vendor_id TEXT,
                job_number TEXT,
                customer_name TEXT,
                staff_user TEXT,
                staff_name TEXT,
                status TEXT DEFAULT 'new',
                created_at TEXT DEFAULT (datetime('now')),
                resolved_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS damage_reports (
                id TEXT PRIMARY KEY, po_number TEXT, po_id TEXT, catalog_id TEXT,
                item_description TEXT, part_number TEXT,
                quantity_damaged INTEGER DEFAULT 1, notes TEXT,
                photo_count INTEGER DEFAULT 0, photos_base64 TEXT,
                vendor_name TEXT, vendor_id TEXT,
                job_number TEXT, customer_name TEXT,
                staff_user TEXT, staff_name TEXT,
                status TEXT DEFAULT 'new',
                created_at TEXT DEFAULT (datetime('now')), resolved_at TEXT
            )
        """)
        
        conn.commit()
    
    # Add email column if it doesn't exist (migration for existing DBs)
    try:
        if USE_PG:
            cursor.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS email TEXT")
            conn.commit()
        else:
            cursor.execute("ALTER TABLE staff ADD COLUMN email TEXT")
            conn.commit()
        print("Added email column to staff table")
    except Exception:
        if USE_PG:
            conn.rollback()
    
    # Seed all staff accounts (survives Render restarts)
    # Each staff member is created if they don't already exist
    staff_seed = [
        ('george', 'George', 'admin', '2ndFix5082', 'george@2ndfix.com.au'),
        ('jim', 'Jim', 'manager', '2ndFix5082', 'jim@2ndfix.com.au'),
        ('cherie', 'Cherie', 'manager', '2ndFix5082', 'accounts@2ndfix.com.au'),
        ('tom', 'Tom', 'manager', '2ndFix5082', 'tom@2ndfix.com.au'),
        ('tyrese', 'Tyrese', 'staff', 'Tyrese123', 'info@2ndfix.com.au'),
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
    
    # Update staff emails that were missing
    cursor.execute("UPDATE staff SET email = 'accounts@2ndfix.com.au' WHERE username = 'cherie' AND (email IS NULL OR email = '')")
    cursor.execute("UPDATE staff SET email = 'info@2ndfix.com.au' WHERE username = 'tyrese' AND (email IS NULL OR email = '')")
    conn.commit()
    
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
    session.permanent = True
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
    
    if 'email' in data:
        email_val = data['email'].strip() if data['email'] else None
        updates.append('email = ?')
        params.append(email_val)
    
    if updates:
        updates.append('updated_at = CURRENT_TIMESTAMP')
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
        # Direct lookup by ID first
        response = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_number}')
        if response.status_code == 200:
            po_id = po_number
        elif response.status_code == 404:
            # Maybe user entered OrderNo instead of ID - try OrderNo search
            search_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/?OrderNo={po_number}')
            if search_resp.status_code == 200:
                orders = search_resp.json()
                if orders:
                    po_id = orders[0].get('ID')
                else:
                    return jsonify({'error': f'PO #{po_number} not found'}), 404
            else:
                return jsonify({'error': f'PO #{po_number} not found'}), 404
        else:
            return jsonify({'error': f'Simpro API error: {response.status_code}'}), 500
        
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
            job_response = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_number}?columns=ID,Name,Customer')
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
        
        # Pre-fetch all cost centres for this job to get custom CC names
        cc_name_map = {}
        if job_number and isinstance(job_number, int):
            po_section_id = assigned_to.get('Section')
            if po_section_id:
                try:
                    cc_list_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_number}/sections/{po_section_id}/costCenters/')
                    if cc_list_resp.status_code == 200:
                        for cc_item in cc_list_resp.json():
                            cc_name_map[cc_item["ID"]] = cc_item.get("Name", cc_item.get("CostCenter", {}).get("Name", "Unknown"))
                except Exception as cc_err:
                    print(f"Error fetching CC names for job {job_number}: {cc_err}")
        
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
            
            # v73: Create one item per ALLOCATION (not per catalog)
            # This splits merged POs into separate lines (e.g. "9 stock + 1 job" → 2 lines)
            if catalog_id:
                try:
                    alloc_response = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/{catalog_id}/allocations/')
                    if alloc_response.status_code == 200:
                        allocations = alloc_response.json()
                        if allocations:
                            for alloc in allocations:
                                qty_obj = alloc.get('Quantity', {})
                                alloc_total = qty_obj.get('Total', 0)
                                alloc_received = qty_obj.get('Received', 0)
                                
                                if alloc_total <= 0:
                                    continue  # Skip zero-qty allocations
                                
                                alloc_assigned = alloc.get('AssignedTo', {})
                                alloc_job = alloc_assigned.get('Job') if isinstance(alloc_assigned, dict) else None
                                alloc_assigned_id = alloc_assigned.get('ID') if isinstance(alloc_assigned, dict) else None
                                
                                # Determine receipt status for THIS allocation
                                if alloc_total > 0 and alloc_received >= alloc_total:
                                    alloc_receipt_status = 'fully_receipted'
                                elif alloc_received > 0:
                                    alloc_receipt_status = 'partially_receipted'
                                else:
                                    alloc_receipt_status = 'not_receipted'
                                
                                item_entry = {
                                    'catalogId': catalog_id,
                                    'partNo': part_no,
                                    'description': description,
                                    'quantityOrdered': alloc_total,
                                    'quantityReceived': alloc_received,
                                    'receiptStatus': alloc_receipt_status,
                                    'allocationType': 'job' if alloc_job else 'stock',
                                    'allocationAssignedToId': alloc_assigned_id,
                                    'storageLocation': None,
                                    'costCentreId': None,
                                    'costCentreName': None,
                                    'jobNumber': None,
                                    'customerName': None,
                                    'jobId': None,
                                    'sectionId': None,
                                }
                                
                                # Extract storage device
                                storage_dev = alloc.get('StorageDevice', {})
                                if isinstance(storage_dev, dict) and storage_dev.get('Name'):
                                    item_entry['storageLocation'] = storage_dev.get('Name')
                                elif isinstance(storage_dev, dict) and storage_dev.get('ID'):
                                    sd_id = storage_dev['ID']
                                    for dev in get_storage_devices():
                                        if dev['ID'] == sd_id:
                                            item_entry['storageLocation'] = dev['Name']
                                            break
                                
                                if alloc_job:
                                    # Job allocation - get job/customer details
                                    job_info = get_job_customer(alloc_job)
                                    item_entry['jobNumber'] = job_info['jobNumber']
                                    item_entry['customerName'] = job_info['customerName']
                                    item_entry['jobId'] = alloc_job
                                    item_entry['sectionId'] = alloc_assigned.get('Section')
                                    cc_obj = alloc_assigned.get('CostCenter', {})
                                    item_entry['costCentreId'] = alloc_assigned_id
                                    item_entry['costCentreName'] = cc_name_map.get(alloc_assigned_id, cc_obj.get('Name', ''))
                                
                                items.append(item_entry)
                        else:
                            # No allocations - add as unknown
                            items.append({
                                'catalogId': catalog_id,
                                'partNo': part_no,
                                'description': description,
                                'quantityOrdered': 0,
                                'quantityReceived': 0,
                                'receiptStatus': 'not_receipted',
                                'allocationType': 'unknown',
                                'allocationAssignedToId': None,
                                'jobNumber': str(job_number) if job_number else None,
                                'customerName': customer_name,
                                'storageLocation': None,
                                'costCentreId': None,
                                'costCentreName': None,
                                'jobId': None,
                                'sectionId': None,
                            })
                except Exception as e:
                    print(f"Error getting allocations for catalog {catalog_id}: {e}")
                    items.append({
                        'catalogId': catalog_id,
                        'partNo': part_no,
                        'description': description,
                        'quantityOrdered': 0,
                        'quantityReceived': 0,
                        'receiptStatus': 'not_receipted',
                        'allocationType': 'unknown',
                        'allocationAssignedToId': None,
                        'jobNumber': str(job_number) if job_number else None,
                        'customerName': customer_name,
                        'storageLocation': None,
                        'costCentreId': None,
                        'costCentreName': None,
                        'jobId': None,
                        'sectionId': None,
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
        po_number = data.get('poNumber', po_id)  # Define early - used in error logging
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
        receipt_allocations = {}  # catalog_id -> {storage_device_id, storage_name, quantity, cc_id, job_id, section_id}
        receipt_alloc_all = {}  # catalog_id -> [list of all allocations with CC info] (v69)
        catalog_items_received = {}  # catalog_id -> True/False (per-catalog ItemsReceived)
        catalog_receipt_id = {}  # catalog_id -> receipt_id (for PATCH ItemsReceived)
        receipted_catalog_ids = set()  # Track which catalogs actually appear in a receipt
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
                                if cat_id:
                                    receipted_catalog_ids.add(cat_id)
                                catalog_items_received[cat_id] = receipt_items_received
                                catalog_receipt_id[cat_id] = receipt_id
                                for alloc in cat.get('Allocations', []):
                                    sd = alloc.get('StorageDevice', {})
                                    sd_id = sd.get('ID') if isinstance(sd, dict) else sd
                                    sd_name = sd.get('Name', 'Unknown') if isinstance(sd, dict) else 'Unknown'
                                    # Extract CC assignment info for 3-step stock move (v69)
                                    assigned_to = alloc.get('AssignedTo', {})
                                    cc_id_val = None
                                    job_id_val = None
                                    section_id_val = None
                                    if isinstance(assigned_to, dict):
                                        cc_id_val = assigned_to.get('ID')
                                        job_ref = assigned_to.get('Job', {})
                                        section_ref = assigned_to.get('Section', {})
                                        job_id_val = job_ref.get('ID') if isinstance(job_ref, dict) else job_ref
                                        section_id_val = section_ref.get('ID') if isinstance(section_ref, dict) else section_ref
                                    alloc_entry = {
                                        'storage_id': sd_id,
                                        'storage_name': sd_name,
                                        'quantity': alloc.get('Quantity', 0),
                                        'cc_id': cc_id_val,
                                        'job_id': job_id_val,
                                        'section_id': section_id_val
                                    }
                                    if cat_id not in receipt_allocations:
                                        receipt_allocations[cat_id] = alloc_entry
                                    if cat_id not in receipt_alloc_all:
                                        receipt_alloc_all[cat_id] = []
                                    receipt_alloc_all[cat_id].append(alloc_entry)
                else:
                    print(f"No receipts found for PO {po_id} - truly not receipted")
            print(f"Server-side receipt check: po_is_receipted={po_is_receipted}, ItemsReceived={items_received_flag}, receipted_catalogs={receipted_catalog_ids}, allocations={receipt_allocations}")
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
            
            # Server-side receipt detection — per-ITEM, not per-PO
            # A PO can be partially receipted (some items in receipt, some not)
            # Only treat an item as receipted if THIS catalog appears in a receipt
            item_in_receipt = catalog_id and (int(catalog_id) in receipted_catalog_ids)
            is_receipted = item_in_receipt or receipt_status == 'fully_receipted'
            
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
            elif is_receipted and item_in_receipt:
                # Receipted AND this specific catalog is in a receipt, but no allocation data found
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
            elif is_receipted and not item_in_receipt:
                # PO has receipts but THIS specific catalog item is NOT in any receipt
                # This happens with partially-supplied POs (e.g. back-ordered items arriving later)
                # Use pre-receipt allocation since this item has no stock yet
                pre_receipt_items.append(item)
                print(f"Catalog {catalog_id}: PO partially receipted but THIS item not in any receipt - using pre-receipt allocation")
            else:
                pre_receipt_items.append(item)
                print(f"Catalog {catalog_id}: Not yet receipted, using pre-receipt allocation")
        
        print(f"Pre-receipt items (allocation): {len(pre_receipt_items)}")
        print(f"Post-receipt items (stock transfer): {len(post_receipt_items)}")
        print(f"Already allocated items: {len(already_allocated_items)}")
        
        # Track partial vs full receipt for status determination
        partial_receipt_detected = False
        
        # ============================================
        # Path 1: Pre-receipt allocation (set storage before Ezybills receipts)
        # CRITICAL v73: Per-allocation matching — knows exactly which allocation to receive
        # The PUT replaces ALL allocations, so must include untouched ones too.
        # ============================================
        
        # v73: Group pre-receipt items by catalogId (same catalog may appear multiple times for merged POs)
        from collections import defaultdict
        catalog_groups = defaultdict(list)
        for item in pre_receipt_items:
            catalog_groups[item.get('catalogId')].append(item)
        
        for catalog_id, group_items in catalog_groups.items():
            # Use first item for metadata
            first_item = group_items[0]
            quantity = sum(gi.get('quantity', 0) for gi in group_items)
            
            allocation_url = f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/{catalog_id}/allocations/'
            
            # Fetch existing allocations
            existing_allocs = []
            try:
                existing_resp = simpro_request('GET', allocation_url)
                if existing_resp.status_code == 200:
                    existing_allocs = existing_resp.json()
                    print(f"[PRE-RECEIPT v73] Existing allocations for catalog {catalog_id}: {existing_allocs}")
            except Exception as ae:
                print(f"[PRE-RECEIPT v73] Error fetching existing allocations: {ae}")
            
            total_existing = sum(
                a.get('Quantity', {}).get('Total', 0) if isinstance(a.get('Quantity'), dict)
                else a.get('Quantity', 0)
                for a in existing_allocs
            ) if existing_allocs else 0
            
            # Check if frontend sent per-allocation info (v73+)
            has_allocation_info = any(gi.get('allocationType') for gi in group_items)
            
            if has_allocation_info and existing_allocs:
                # v73 per-allocation logic
                # Separate received items into job allocations and stock pool
                job_received = {}  # allocationAssignedToId -> qty
                stock_received_total = 0
                
                for gi in group_items:
                    aid = gi.get('allocationAssignedToId')
                    qty = gi.get('quantity', 0)
                    atype = gi.get('allocationType', 'stock')
                    if aid and atype == 'job':
                        job_received[aid] = job_received.get(aid, 0) + qty
                    else:
                        stock_received_total += qty
                
                payload = []
                remaining_stock_to_deduct = stock_received_total
                
                for ea in existing_allocs:
                    ea_qty_obj = ea.get('Quantity', {})
                    ea_qty = float(ea_qty_obj.get('Total', 0) if isinstance(ea_qty_obj, dict) else ea_qty_obj)
                    ea_storage = ea.get('StorageDevice', {}).get('ID', 3) if isinstance(ea.get('StorageDevice'), dict) else ea.get('StorageDevice', 3)
                    ea_assigned = ea.get('AssignedTo', {})
                    ea_assigned_id = ea_assigned.get('ID') if isinstance(ea_assigned, dict) else None
                    
                    if ea_assigned_id and ea_assigned_id in job_received:
                        # Job allocation being received
                        recv_qty = job_received.pop(ea_assigned_id)
                        remaining = ea_qty - recv_qty
                        
                        if recv_qty > 0:
                            entry = {'StorageDevice': int(storage_device_id), 'Quantity': float(recv_qty), 'AssignedTo': ea_assigned_id}
                            payload.append(entry)
                        if remaining > 0:
                            entry = {'StorageDevice': int(ea_storage), 'Quantity': float(remaining), 'AssignedTo': ea_assigned_id}
                            payload.append(entry)
                            partial_receipt_detected = True
                    elif not ea_assigned_id and remaining_stock_to_deduct > 0:
                        # Stock allocation — deduct from stock pool
                        deduct = min(remaining_stock_to_deduct, ea_qty)
                        remaining_stock_to_deduct -= deduct
                        remaining = ea_qty - deduct
                        
                        if deduct > 0:
                            payload.append({'StorageDevice': int(storage_device_id), 'Quantity': float(deduct)})
                        if remaining > 0:
                            payload.append({'StorageDevice': int(ea_storage), 'Quantity': float(remaining)})
                            partial_receipt_detected = True
                    else:
                        # Not being received — keep as-is
                        entry = {'StorageDevice': int(ea_storage), 'Quantity': float(ea_qty)}
                        if ea_assigned_id:
                            entry['AssignedTo'] = ea_assigned_id
                        payload.append(entry)
                        if ea_qty > 0:
                            partial_receipt_detected = True
                
                total_payload = sum(e['Quantity'] for e in payload)
                print(f"[PRE-RECEIPT v73] Per-allocation: job_received={job_received}, stock_deducted={stock_received_total - remaining_stock_to_deduct}")
                print(f"[PRE-RECEIPT v73] Payload total={total_payload}, existing total={total_existing}")
                if abs(total_payload - total_existing) > 0.01:
                    print(f"WARNING: Total mismatch! Existing={total_existing}, Payload={total_payload}")
            
            elif not existing_allocs or quantity >= total_existing:
                # Simple case: receiving ALL items or no existing data
                payload = [{'StorageDevice': int(storage_device_id), 'Quantity': float(quantity if quantity > 0 else total_existing)}]
                print(f"[PRE-RECEIPT] Full receipt: {quantity} of {total_existing} items")
            else:
                # v72 fallback: deduct from stock first, preserve job allocations
                partial_receipt_detected = True
                payload = [{'StorageDevice': int(storage_device_id), 'Quantity': float(quantity)}]
                
                stock_allocs_list = [a for a in existing_allocs if not a.get('AssignedTo') or not a.get('AssignedTo', {}).get('ID')]
                job_allocs_list = [a for a in existing_allocs if a.get('AssignedTo') and a.get('AssignedTo', {}).get('ID')]
                
                qty_to_deduct = float(quantity)
                for ea in stock_allocs_list + job_allocs_list:
                    ea_qty_obj = ea.get('Quantity', {})
                    ea_qty = ea_qty_obj.get('Total', 0) if isinstance(ea_qty_obj, dict) else ea_qty_obj
                    ea_storage = ea.get('StorageDevice', {}).get('ID', 3) if isinstance(ea.get('StorageDevice'), dict) else ea.get('StorageDevice', 3)
                    ea_assigned_id = ea.get('AssignedTo', {}).get('ID') if isinstance(ea.get('AssignedTo'), dict) else None
                    
                    deduct = min(qty_to_deduct, float(ea_qty))
                    leftover = float(ea_qty) - deduct
                    qty_to_deduct -= deduct
                    
                    if leftover > 0:
                        entry = {'StorageDevice': int(ea_storage), 'Quantity': leftover}
                        if ea_assigned_id:
                            entry['AssignedTo'] = ea_assigned_id
                        payload.append(entry)
                    elif deduct == 0 and float(ea_qty) > 0:
                        entry = {'StorageDevice': int(ea_storage), 'Quantity': float(ea_qty)}
                        if ea_assigned_id:
                            entry['AssignedTo'] = ea_assigned_id
                        payload.append(entry)
                
                total_in_payload = sum(a['Quantity'] for a in payload)
                print(f"[PRE-RECEIPT v72 fallback] Partial: {quantity} of {total_existing}. Payload total={total_in_payload}")
            
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
                    'method': 'pre_receipt_allocation',
                    'message': f'Allocated to storage ({"verified" if verified else "pending verification"})'
                })
                success_count += 1
            else:
                error_msg = f'Simpro API error: {response.status_code}'
                try:
                    error_data = response.json()
                    error_msg = str(error_data)
                except:
                    error_msg = response.text[:200]
                
                results.append({
                    'catalogId': catalog_id,
                    'success': False,
                    'error': error_msg,
                    'method': 'pre_receipt_allocation'
                })
                
                # Log error
                try:
                    err_conn = get_db()
                    err_cursor = err_conn.cursor()
                    err_cursor.execute(
                        '''INSERT INTO error_logs (error_type, po_number, catalog_id, staff_user, error_code, error_message, request_payload, response_body, endpoint)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        ('allocation', str(po_number), str(catalog_id), session.get('display_name', 'Unknown'),
                         response.status_code, error_msg,
                         json.dumps(payload), response.text[:500],
                         allocation_url))
                    err_conn.commit()
                    err_conn.close()
                except Exception as log_err:
                    print(f"Error logging failed: {log_err}")

        # ============================================
        # Path 2: Post-receipt stock transfer (move from current location to destination)
        # Uses POST /stockTransfers/ endpoint — ONE item per request to avoid Simpro batch bug
        # (Simpro validates qty of item 1 against stock of item 2 when batched — API Forum #2409)
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
                    print(f"Skipping service item: {part_no} - {desc}")
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
            
            # ============================================
            # v69: 3-step CC stock move for post-receipt items
            # CC-allocated stock does NOT appear in storage device InventoryCount.
            # Instead of checking InventoryCount (which returns 0), we use receipt
            # allocation data + 3-step CC stock move:
            #   1. Un-assign from CC at source storage
            #   2. Stock transfer from source to destination
            #   3. Re-assign to CC at destination storage
            # ============================================
            
            print(f"[v69] Receipt alloc_all keys: {list(receipt_alloc_all.keys())}")
            print(f"[v69] Receipt allocations: {receipt_allocations}")
            
            for item in post_receipt_items:
                catalog_id = item.get('catalogId')
                part_no = item.get('partNo', '')
                desc = item.get('description', '')
                quantity = item.get('quantity', 1)
                dest_storage_id = int(storage_device_id)
                
                if quantity <= 0:
                    quantity = 1
                
                # Get receipt allocation(s) for this catalog
                allocs = receipt_alloc_all.get(catalog_id) or receipt_alloc_all.get(int(catalog_id)) if catalog_id else None
                if not allocs:
                    allocs = receipt_alloc_all.get(str(catalog_id))
                
                # Also try single allocation from receipt_allocations
                if not allocs:
                    single_alloc = receipt_allocations.get(catalog_id) or receipt_allocations.get(int(catalog_id)) if catalog_id else None
                    if not single_alloc:
                        single_alloc = receipt_allocations.get(str(catalog_id))
                    if single_alloc:
                        allocs = [single_alloc]
                
                if not allocs:
                    # No allocation data found - fetch receipt detail fresh
                    print(f"[v69] No allocation data for catalog {catalog_id}, fetching receipt detail...")
                    r_id = catalog_receipt_id.get(catalog_id) or catalog_receipt_id.get(int(catalog_id) if catalog_id else None)
                    if not r_id:
                        r_id = first_receipt_id if 'first_receipt_id' in dir() else None
                    if r_id:
                        try:
                            rd_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/receipts/{r_id}')
                            if rd_resp.status_code == 200:
                                rd = rd_resp.json()
                                for cat_item in rd.get('Catalogs', []):
                                    cid = cat_item.get('Catalog', {}).get('ID')
                                    if cid and int(cid) == int(catalog_id):
                                        allocs = []
                                        for al in cat_item.get('Allocations', []):
                                            sd = al.get('StorageDevice', {})
                                            sd_id = sd.get('ID') if isinstance(sd, dict) else sd
                                            sd_nm = sd.get('Name', 'Unknown') if isinstance(sd, dict) else 'Unknown'
                                            at = al.get('AssignedTo', {})
                                            cc_v = None
                                            job_v = None
                                            sec_v = None
                                            if isinstance(at, dict):
                                                cc_v = at.get('ID')
                                                jr = at.get('Job', {})
                                                sr = at.get('Section', {})
                                                job_v = jr.get('ID') if isinstance(jr, dict) else jr
                                                sec_v = sr.get('ID') if isinstance(sr, dict) else sr
                                            allocs.append({
                                                'storage_id': sd_id,
                                                'storage_name': sd_nm,
                                                'quantity': al.get('Quantity', 0),
                                                'cc_id': cc_v,
                                                'job_id': job_v,
                                                'section_id': sec_v
                                            })
                                        break
                        except Exception as fetch_err:
                            print(f"[v69] Error fetching receipt detail: {fetch_err}")
                
                if not allocs:
                    print(f"[v69] WARN: No receipt allocation data for catalog {catalog_id} ({part_no}) - cannot process")
                    results.append({
                        'catalogId': catalog_id,
                        'success': False,
                        'quantity': quantity,
                        'method': 'cc_stock_move_no_alloc',
                        'error': 'No receipt allocation data found for this item. Cannot determine CC assignment.'
                    })
                    continue
                
                print(f"[v69] Processing {part_no} (catalog {catalog_id}) x{quantity}, dest={dest_storage_id}, allocs={allocs}")
                
                item_success = True
                item_messages = []
                remaining_qty = float(quantity)
                
                for alloc_info in allocs:
                    if remaining_qty <= 0:
                        break
                    
                    source_storage_id = alloc_info.get('storage_id')
                    source_storage_name = alloc_info.get('storage_name', 'Unknown')
                    alloc_qty = float(alloc_info.get('quantity', 0))
                    cc_id = alloc_info.get('cc_id')
                    job_id = alloc_info.get('job_id')
                    section_id = alloc_info.get('section_id')
                    
                    # v71: Cross-reference with ACTUAL CC stock to get TRUE current storage location
                    # Receipt allocations are STALE - they never update after stock moves (Simpro conflict #2)
                    # Retry loop: Simpro can take >3s to populate AssignedBreakdown after ItemsReceived
                    if cc_id and job_id and section_id:
                        cc_stock_url = f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/{catalog_id}"
                        cc_stock_found = False
                        max_cc_retries = 5
                        for cc_retry in range(max_cc_retries):
                            try:
                                print(f"[v71] Checking TRUE location via CC stock (attempt {cc_retry+1}/{max_cc_retries}): {cc_stock_url}")
                                cc_stock_resp = simpro_request('GET', cc_stock_url)
                                if cc_stock_resp.status_code == 200:
                                    cc_stock_data = cc_stock_resp.json()
                                    true_breakdown = cc_stock_data.get('AssignedBreakdown', [])
                                    # Check if any entry has Quantity > 0
                                    has_stock = False
                                    if true_breakdown:
                                        for tb in true_breakdown:
                                            ts = tb.get('Storage', {})
                                            ts_id = ts.get('ID') if isinstance(ts, dict) else ts
                                            ts_name = ts.get('Name', 'Unknown') if isinstance(ts, dict) else 'Unknown'
                                            ts_qty = float(tb.get('Quantity', 0))
                                            if ts_qty > 0:
                                                if ts_id != source_storage_id:
                                                    print(f"[v71] CORRECTED source: {source_storage_name}({source_storage_id}) -> {ts_name}({ts_id})")
                                                source_storage_id = ts_id
                                                source_storage_name = ts_name
                                                alloc_qty = ts_qty
                                                has_stock = True
                                                break
                                    if has_stock:
                                        if cc_retry > 0:
                                            print(f"[v71] CC stock appeared after {cc_retry} retries for catalog {catalog_id}")
                                        cc_stock_found = True
                                        break
                                    else:
                                        # AssignedBreakdown empty or all quantities 0
                                        if cc_retry < max_cc_retries - 1:
                                            print(f"[v71] CC stock retry {cc_retry+1}/{max_cc_retries} for catalog {catalog_id} — AssignedBreakdown empty, waiting 3s...")
                                            time.sleep(3)
                                        else:
                                            print(f"[v71] CC stock still empty after {max_cc_retries} retries for catalog {catalog_id} — using receipt allocs")
                                else:
                                    print(f"[v71] CC stock lookup returned {cc_stock_resp.status_code} - keeping receipt allocs")
                                    break  # Non-200 status, no point retrying
                            except Exception as cc_err:
                                print(f"[v71] CC stock lookup error: {cc_err} - using receipt allocation")
                                break  # Exception, no point retrying
                    
                    move_qty = min(remaining_qty, alloc_qty) if alloc_qty > 0 else remaining_qty
                    if move_qty <= 0:
                        move_qty = remaining_qty
                    
                    # SPECIAL CASE: destination == source storage - no move needed!
                    if source_storage_id and int(source_storage_id) == dest_storage_id:
                        print(f"[v69] {part_no}: dest == source ({dest_storage_id}), no move needed")
                        item_messages.append(f'Stock already at {source_storage_name} (no move needed)')
                        remaining_qty -= move_qty
                        continue
                    
                    if not source_storage_id:
                        source_storage_id = STOCK_HOLDING_ID
                        source_storage_name = 'Stock Holding'
                    
                    print(f"[v69] 3-step CC move for {part_no} x{move_qty}: {source_storage_name}({source_storage_id}) -> {storage_name}({dest_storage_id})")
                    print(f"[v69] CC info: job={job_id}, section={section_id}, cc={cc_id}")
                    
                    step_failed = False
                    
                    # STEP 1: Un-assign from CC at source (frees stock into InventoryCount)
                    if cc_id and job_id and section_id:
                        try:
                            print(f"[v69] Step 1: Un-assign catalog {catalog_id} from CC {cc_id} at storage {source_storage_id}")
                            unassign_resp = simpro_request(
                                'PATCH',
                                f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/{catalog_id}',
                                json={'AssignedBreakdown': [{'Storage': int(source_storage_id), 'Quantity': 0}]}
                            )
                            print(f"[v69] Step 1 response: {unassign_resp.status_code} - {unassign_resp.text[:200] if unassign_resp.text else ''}")
                            if unassign_resp.status_code not in (200, 204):
                                print(f"[v69] Step 1 FAILED: {unassign_resp.status_code}")
                                step_failed = True
                                item_messages.append(f'Step 1 failed (un-assign): HTTP {unassign_resp.status_code}')
                        except Exception as step1_err:
                            print(f"[v69] Step 1 ERROR: {step1_err}")
                            step_failed = True
                            item_messages.append(f'Step 1 error: {str(step1_err)}')
                    else:
                        print(f"[v69] No CC info - skipping step 1, will attempt direct transfer")
                    
                    # STEP 2: Stock transfer from source to destination
                    if not step_failed:
                        try:
                            transfer_payload = {
                                'SourceStorageDeviceID': int(source_storage_id),
                                'Items': [{
                                    'CatalogID': int(catalog_id),
                                    'DestinationStorageDeviceID': int(dest_storage_id),
                                    'Quantity': move_qty
                                }]
                            }
                            print(f"[v69] Step 2: Stock transfer {json.dumps(transfer_payload)}")
                            transfer_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/stockTransfer/', json=transfer_payload)
                            print(f"[v69] Step 2 response: {transfer_resp.status_code} - {transfer_resp.text[:200] if transfer_resp.text else ''}")
                            if transfer_resp.status_code not in (200, 201, 204):
                                print(f"[v69] Step 2 FAILED: {transfer_resp.status_code}")
                                step_failed = True
                                err_detail = ''
                                try:
                                    ed = transfer_resp.json()
                                    if isinstance(ed, dict) and 'Message' in ed:
                                        err_detail = ed['Message']
                                except:
                                    err_detail = transfer_resp.text[:200] if transfer_resp.text else ''
                                item_messages.append(f'Step 2 failed (transfer): HTTP {transfer_resp.status_code} {err_detail}')
                                
                                # Rollback step 1 if we un-assigned
                                if cc_id and job_id and section_id:
                                    try:
                                        print(f"[v69] Rolling back step 1: re-assigning to CC at source")
                                        rb_resp = simpro_request(
                                            'POST',
                                            f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/',
                                            json={'Catalog': int(catalog_id), 'AssignedBreakdown': [{'Storage': int(source_storage_id), 'Quantity': move_qty}]}
                                        )
                                        print(f"[v69] Rollback response: {rb_resp.status_code}")
                                    except Exception as rb_err:
                                        print(f"[v69] Rollback failed: {rb_err}")
                        except Exception as step2_err:
                            print(f"[v69] Step 2 ERROR: {step2_err}")
                            step_failed = True
                            item_messages.append(f'Step 2 error: {str(step2_err)}')
                    
                    # STEP 3: Re-assign to CC at destination
                    if not step_failed and cc_id and job_id and section_id:
                        try:
                            print(f"[v69] Step 3: Re-assign catalog {catalog_id} to CC {cc_id} at storage {dest_storage_id}")
                            reassign_resp = simpro_request(
                                'POST',
                                f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/',
                                json={'Catalog': int(catalog_id), 'AssignedBreakdown': [{'Storage': int(dest_storage_id), 'Quantity': move_qty}]}
                            )
                            print(f"[v69] Step 3 response: {reassign_resp.status_code} - {reassign_resp.text[:200] if reassign_resp.text else ''}")
                            if reassign_resp.status_code not in (200, 201, 204):
                                print(f"[v69] Step 3 FAILED: {reassign_resp.status_code}")
                                step_failed = True
                                item_messages.append(f'Step 3 failed (re-assign): HTTP {reassign_resp.status_code}')
                        except Exception as step3_err:
                            print(f"[v69] Step 3 ERROR: {step3_err}")
                            step_failed = True
                            item_messages.append(f'Step 3 error: {str(step3_err)}')
                    elif not step_failed and not (cc_id and job_id and section_id):
                        print(f"[v69] No CC info - skipping step 3 (re-assign)")
                        item_messages.append('Transferred (no CC re-assignment - CC info not available)')
                    
                    if step_failed:
                        item_success = False
                    else:
                        if cc_id and job_id and section_id:
                            item_messages.append(f'3-step CC move OK: {source_storage_name} -> {storage_name}')
                        else:
                            item_messages.append(f'Direct transfer OK: {source_storage_name} -> {storage_name}')
                        remaining_qty -= move_qty
                
                # Record result
                if item_success:
                    results.append({
                        'catalogId': catalog_id,
                        'success': True,
                        'quantity': quantity,
                        'verified': True,
                        'method': 'cc_stock_move',
                        'message': '; '.join(item_messages) if item_messages else f'Moved to {storage_name}'
                    })
                    success_count += 1
                    print(f"[v69] SUCCESS: {part_no} x{quantity} -> {storage_name}")
                else:
                    error_summary = '; '.join(item_messages) if item_messages else 'Unknown error in CC stock move'
                    print(f"[v69] FAILED: {part_no} - {error_summary}")
                    
                    try:
                        import json as json_mod
                        err_conn = get_db()
                        err_cursor = err_conn.cursor()
                        err_cursor.execute(
                            """INSERT INTO error_logs (error_type, po_number, catalog_id, staff_user, error_code, error_message, request_payload, response_body, endpoint)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            ('cc_stock_move', str(po_number), str(catalog_id), session.get('display_name', 'Unknown'),
                             0, error_summary,
                             json.dumps({'allocs': str(allocs), 'dest': dest_storage_id}), '',
                             'v69_3step_cc_move'))
                        err_conn.commit()
                        err_conn.close()
                    except Exception as log_err:
                        print(f"Error logging failed: {log_err}")
                    
                    results.append({
                        'catalogId': catalog_id,
                        'success': False,
                        'quantity': quantity,
                        'error': error_summary,
                        'method': 'cc_stock_move'
                    })

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
        status_set = None
        if success_count > 0 and pre_receipt_items:
            try:
                # Always set 239 (GOODS RECEIVED) when any items are allocated
                # Kelly's KPro integration handles partial/complete status logic from here
                print(f"=== SETTING GOODS RECEIVED STATUS for PO {po_id} ===")
                gr_response = simpro_request('PATCH', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}', json={'Status': 239})
                print(f"Goods Received API Response: {gr_response.status_code}")
                if gr_response.status_code == 204:
                    goods_received_set = True
                    status_set = 239
                    print(f"\u2705 Goods Received status set successfully for PO {po_id}")
                else:
                    print(f"\u26a0\ufe0f Goods Received status update returned: {gr_response.status_code} - {gr_response.text}")
            except Exception as gr_err:
                print(f"\u26a0\ufe0f Failed to set PO status: {gr_err}")
        
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


@app.route('/api/stock-search', methods=['POST'])
@login_required
def stock_search():
    """Search for stock by PO or Job number - returns items with TRUE locations.
    
    Uses multiple data sources for accuracy:
    1. PO allocation data (job/section/CC info + PO storage)
    2. CC stock (actual assigned quantities and locations for job stock)
    3. Storage device stock (fallback for items received outside normal flow)
    """
    try:
        data = request.get_json()
        search_type = data.get('searchType', 'po')
        search_value = data.get('searchValue', '')
        
        if not search_value:
            return jsonify({'error': 'Please enter a number'}), 400
        
        po_ids = []
        
        if search_type == 'job':
            # Job search: look up job, iterate sections/cost centres, get stock
            job_id_val = search_value.strip()
            
            # Step 1: Look up job by ID
            job_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id_val}?columns=ID,Name,Customer,Site')
            if job_resp.status_code != 200:
                return jsonify({'error': f'Job {job_id_val} not found'}), 400
            jd = job_resp.json()
            cust = jd.get('Customer', {})
            customer_name = ''
            if isinstance(cust, dict):
                customer_name = cust.get('CompanyName', cust.get('GivenName', ''))
            job_name = jd.get('Name', str(job_id_val))
            job_info = {
                'jobNumber': job_name,
                'customerName': customer_name,
            }
            
            # Step 2: Get sections for the job
            sec_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id_val}/sections/')
            sections = []
            if sec_resp.status_code == 200:
                sections = sec_resp.json()
            
            all_items = []
            collected_po_ids = set()
            
            for section in sections:
                sid = section.get('ID')
                if not sid:
                    continue
                
                # Step 3: Get cost centres for this section
                cc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id_val}/sections/{sid}/costCenters/')
                cost_centres = []
                if cc_resp.status_code == 200:
                    cost_centres = cc_resp.json()
                
                for cc in cost_centres:
                    ccid = cc.get('ID')
                    if not ccid:
                        continue
                    
                    # Step 4: Get stock for this cost centre
                    stock_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id_val}/sections/{sid}/costCenters/{ccid}/stock/')
                    if stock_resp.status_code != 200:
                        continue
                    cc_stocks = stock_resp.json()
                    
                    # Step 5: Try to get vendor orders (POs) for this cost centre
                    po_order_no = ''
                    try:
                        vo_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id_val}/sections/{sid}/costCenters/{ccid}/vendorOrders/')
                        if vo_resp.status_code == 200:
                            vos = vo_resp.json()
                            for vo in vos:
                                vo_id = vo.get('ID')
                                vo_order_no = vo.get('OrderNo', '')
                                if vo_id:
                                    collected_po_ids.add(str(vo_id))
                                if vo_order_no and not po_order_no:
                                    po_order_no = vo_order_no
                    except Exception:
                        pass
                    
                    # Step 6: Build items from CC stock
                    for s in cc_stocks:
                        cat = s.get('Catalog', {})
                        cat_id = cat.get('ID')
                        if not cat_id:
                            continue
                        part_no = cat.get('PartNo', '?')
                        name = cat.get('Name', '')
                        qty_info = s.get('Quantity', {})
                        assigned_qty = qty_info.get('Assigned', 0)
                        breakdown = s.get('AssignedBreakdown', [])
                        
                        # Find storage with highest quantity
                        best_storage_id = None
                        best_storage_name = 'Unknown'
                        best_qty = 0
                        for bd in breakdown:
                            bd_qty = bd.get('Quantity', 0)
                            if bd_qty > best_qty:
                                best_qty = bd_qty
                                best_storage_id = bd.get('Storage', {}).get('ID')
                                best_storage_name = bd.get('Storage', {}).get('Name', 'Unknown')
                        
                        if not best_storage_id and breakdown:
                            best_storage_id = breakdown[0].get('Storage', {}).get('ID')
                            best_storage_name = breakdown[0].get('Storage', {}).get('Name', 'Unknown')
                        
                        true_qty = best_qty if best_qty > 0 else assigned_qty
                        # v85 fix: awaiting only when nothing assigned — empty breakdown ≠ not received
                        awaiting = assigned_qty <= 0
                        
                        item_data = {
                            'catalogId': cat_id,
                            'partNo': part_no,
                            'description': name,
                            'storageId': best_storage_id,
                            'storageName': best_storage_name,
                            'quantity': true_qty,
                            'quantityOrdered': 0,
                            'awaitingReceipt': awaiting,
                            'jobId': int(job_id_val),
                            'sectionId': sid,
                            'costCentreId': ccid,
                            'poOrderNo': po_order_no,
                        }
                        all_items.append(item_data)
                        print(f"  Job stock: {part_no}: storage={best_storage_name}, qty={true_qty}, awaiting={awaiting}")
            
            received_items = [i for i in all_items if not i['awaitingReceipt']]
            awaiting_items = [i for i in all_items if i['awaitingReceipt']]
            
            po_list = [{'poId': pid} for pid in collected_po_ids]
            
            result = {
                'job': job_info,
                'pos': po_list,
                'receivedCount': len(received_items),
                'awaitingCount': len(awaiting_items),
                'items': all_items
            }
            
            return jsonify(result)
        else:
            po_ids = [search_value]
        
        all_items = []
        job_info = None
        job_id = None
        section_id = None
        cc_id = None
        cc_stock_map = {}  # catalogId -> {assigned, storageId, storageName}
        
        for po_id in po_ids:
            # Step 1: Get PO details
            po_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}')
            if po_resp.status_code != 200:
                continue
            po_data = po_resp.json()
            po_order_no = po_data.get('OrderNo', str(po_id))
            
            # Step 2: Get catalog items and their allocations
            cat_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/')
            if cat_resp.status_code != 200:
                continue
            catalogs = cat_resp.json()
            
            # Get allocation for first item to find job/section/CC
            for cat_item in catalogs:
                cat_id = cat_item.get('Catalog', {}).get('ID')
                if not cat_id:
                    continue
                alloc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/{cat_id}/allocations/')
                if alloc_resp.status_code == 200:
                    allocs = alloc_resp.json()
                    if allocs:
                        assigned_to = allocs[0].get('AssignedTo', {})
                        job_id = assigned_to.get('Job')
                        section_id = assigned_to.get('Section')
                        cc_id = assigned_to.get('ID')
                        if job_id:
                            break
            
            # Step 3: Get job info and CC stock in bulk (one API call for all items)
            if job_id and section_id and cc_id:
                # Get job info
                job_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}')
                if job_resp.status_code == 200:
                    jd = job_resp.json()
                    cust = jd.get('Customer', {})
                    customer_name = ''
                    if isinstance(cust, dict):
                        customer_name = cust.get('CompanyName', cust.get('GivenName', ''))
                    job_info = {
                        'jobNumber': jd.get('Name', str(job_id)),
                        'customerName': customer_name,
                    }
                
                # Get ALL CC stock in one call
                cc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/')
                if cc_resp.status_code == 200:
                    cc_stocks = cc_resp.json()
                    for s in cc_stocks:
                        cat = s.get('Catalog', {})
                        cat_id = cat.get('ID')
                        qty_info = s.get('Quantity', {})
                        assigned_qty = qty_info.get('Assigned', 0)
                        breakdown = s.get('AssignedBreakdown', [])
                        
                        # Find storage with highest quantity
                        best_storage_id = None
                        best_storage_name = 'Unknown'
                        best_qty = 0
                        for bd in breakdown:
                            bd_qty = bd.get('Quantity', 0)
                            if bd_qty > best_qty:
                                best_qty = bd_qty
                                best_storage_id = bd.get('Storage', {}).get('ID')
                                best_storage_name = bd.get('Storage', {}).get('Name', 'Unknown')
                        
                        # Even if assigned=0, remember the storage reference
                        if not best_storage_id and breakdown:
                            best_storage_id = breakdown[0].get('Storage', {}).get('ID')
                            best_storage_name = breakdown[0].get('Storage', {}).get('Name', 'Unknown')
                        
                        cc_stock_map[cat_id] = {
                            'assigned': assigned_qty,
                            'storageId': best_storage_id,
                            'storageName': best_storage_name,
                            'quantity': best_qty if best_qty > 0 else assigned_qty,
                        }
                    print(f"CC stock map: {json.dumps({k: v for k, v in cc_stock_map.items()}, default=str)}")
            
            # Step 4: Build item list
            for cat_item in catalogs:
                cat_catalog = cat_item.get('Catalog', {})
                catalog_id = cat_catalog.get('ID')
                part_no = cat_catalog.get('PartNo', '?')
                name = cat_catalog.get('Name', '')
                
                if not catalog_id:
                    continue
                
                # Get allocation for this specific item
                alloc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/{catalog_id}/allocations/')
                alloc_data = []
                if alloc_resp.status_code == 200:
                    alloc_data = alloc_resp.json()
                alloc = alloc_data[0] if alloc_data else {}
                po_qty_total = alloc.get('Quantity', {}).get('Total', 0)
                po_qty_received = alloc.get('Quantity', {}).get('Received', 0)
                po_storage = alloc.get('StorageDevice', {})
                
                # Determine TRUE location and received status
                cc_data = cc_stock_map.get(catalog_id, {})
                cc_assigned = cc_data.get('assigned', 0)
                cc_qty = cc_data.get('quantity', 0)
                
                # Priority: CC stock assigned > 0 = definitely received and located
                if cc_assigned > 0:
                    true_storage_id = cc_data['storageId']
                    true_storage_name = cc_data['storageName']
                    true_qty = cc_qty
                    awaiting = False
                elif po_qty_received > 0:
                    # PO says received but CC shows 0 assigned
                    # CC assigned qty is authoritative - if 0, item has been consumed/moved/not actually there
                    # Mark as awaiting receipt since we cannot confirm physical location
                    true_storage_id = po_storage.get('ID')
                    true_storage_name = po_storage.get('Name', 'Unknown')
                    true_qty = 0
                    awaiting = True
                    print(f"  {part_no}: PO received but CC assigned=0, marking as awaiting")
                else:
                    # PO says 0 received AND CC says 0 assigned
                    # CC assigned qty is authoritative - if 0, item is truly awaiting receipt
                    # Do NOT check storage device as it may contain residual/unrelated stock data
                    true_storage_id = po_storage.get('ID')
                    true_storage_name = po_storage.get('Name', 'Unknown')
                    true_qty = 0
                    awaiting = True
                
                item_data = {
                    'catalogId': catalog_id,
                    'partNo': part_no,
                    'description': name,
                    'storageId': true_storage_id,
                    'storageName': true_storage_name,
                    'quantity': true_qty,
                    'quantityOrdered': po_qty_total,
                    'awaitingReceipt': awaiting,
                    'jobId': job_id,
                    'sectionId': section_id,
                    'costCentreId': cc_id,
                    'poOrderNo': po_order_no,

                }
                all_items.append(item_data)
                print(f"  {part_no}: storage={true_storage_name}, qty={true_qty}, awaiting={awaiting}")
        
        received_items = [i for i in all_items if not i['awaitingReceipt']]
        awaiting_items = [i for i in all_items if i['awaitingReceipt']]
        
        result = {
            'job': job_info,
            'pos': [{'poId': pid} for pid in po_ids],
            'receivedCount': len(received_items),
            'awaitingCount': len(awaiting_items),
            'items': all_items
        }
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Stock search error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



def get_all_storage_devices():
    """Fetch all storage devices from Simpro API, with 60-second cache."""
    global _storage_devices_cache, _storage_devices_cache_time
    now = time.time()
    if _storage_devices_cache is not None and (now - _storage_devices_cache_time) < 60:
        return _storage_devices_cache
    try:
        resp = simpro_request('GET', f'/companies/{COMPANY_ID}/storageDevices/?pageSize=200')
        if resp.status_code == 200:
            devices = {}
            for dev in resp.json():
                did = dev.get('ID')
                dname = dev.get('Name', f'Device {did}')
                if did:
                    devices[did] = dname
            _storage_devices_cache = devices
            _storage_devices_cache_time = now
            return devices
    except Exception as e:
        print(f'get_all_storage_devices error: {e}')
    # Return cached version even if stale, or empty dict
    return _storage_devices_cache or {}


@app.route('/api/stock-part-search', methods=['POST'])
@login_required
def stock_part_search():
    """Search for a part number across all storage devices (parallel, fast)."""
    from urllib.parse import quote as url_quote
    import concurrent.futures
    try:
        data = request.get_json()
        part_number = data.get('partNumber', '').strip()

        if not part_number:
            return jsonify({'error': 'Please enter a part number'}), 400

        # Dynamically fetch all storage devices (cached for 60s)
        STORAGE_DEVICES = get_all_storage_devices()

        search_lower = part_number.lower()
        encoded = url_quote(str(part_number), safe='')

        def search_device(sid_sname):
            sid, sname = sid_sname
            try:
                resp = simpro_request('GET', f'/companies/{COMPANY_ID}/storageDevices/{sid}/stock/?columns=Catalog,InventoryCount&Catalog.PartNo={encoded}')
                results = []
                if resp.status_code == 200:
                    batch = resp.json()
                    for s in batch:
                        inv = s.get('InventoryCount', 0)
                        if inv > 0:
                            cat = s.get('Catalog', {})
                            pno = cat.get('PartNo', '') or ''
                            if search_lower in pno.lower():
                                results.append({
                                    'catalogId': cat.get('ID'),
                                    'partNo': pno,
                                    'description': cat.get('Name', ''),
                                    'storageId': sid,
                                    'storageName': sname,
                                    'quantity': inv
                                })
                return results
            except Exception as e:
                print(f'stock_part_search device {sid} error: {e}')
                return []

        items = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(search_device, (sid, sname)): sid for sid, sname in STORAGE_DEVICES.items()}
            for future in concurrent.futures.as_completed(futures, timeout=15):
                try:
                    items.extend(future.result())
                except Exception:
                    pass

        # Sort: highest quantity first
        items.sort(key=lambda x: x.get('quantity', 0), reverse=True)

        return jsonify({'items': items})
    except Exception as e:
        print(f'Part search error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/allocate-from-stock', methods=['POST'])
@login_required
def allocate_from_stock():
    """Move selected stock items to a destination storage and optionally allocate to job.
    Each item can have a different source storage. Uses 3-step CC move for job-allocated items."""
    try:
        data = request.get_json()
        dest_id = data.get('destId')
        dest_name = data.get('destName', 'Unknown')
        job_number = data.get('jobNumber', '')
        customer_name = data.get('customerName', '')
        items = data.get('items', [])
        staff_member = session.get('username', 'unknown')
        staff_name = session.get('display_name', staff_member)
        target_job_id = data.get('targetJobId', '')
        
        if not dest_id or not items:
            return jsonify({"error": "Missing destination or items"}), 400
        
        print(f"=== ALLOCATE FROM STOCK ===")
        print(f"Dest: {dest_name} (ID:{dest_id}) | Items: {len(items)} | Staff: {staff_name}")
        
        results = []
        success_count = 0
        
        for item in items:
            catalog_id = item.get('catalogId')
            quantity = item.get('quantity', 1)
            part_no = item.get('partNo', '?')
            source_id = item.get('sourceId')
            source_name = item.get('sourceName', 'Unknown')
            job_id = item.get('jobId')
            section_id = item.get('sectionId')
            cost_centre_id = item.get('costCentreId')
            
            if not catalog_id:
                results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": "Missing catalog ID"})
                continue
            
            print(f"\n--- {part_no} (Cat:{catalog_id}) x{quantity}: {source_name}({source_id}) -> {dest_name}({dest_id}) ---")
            
            # Skip if source == destination
            if source_id and str(source_id) == str(dest_id):
                print(f"  Source == Dest, no move needed")
                results.append({"catalogId": catalog_id, "partNo": part_no, "success": True, "method": "no_move_needed"})
                success_count += 1
                continue
            
            # CC confirmation required - block silent auto-allocation
            if target_job_id and not (section_id and cost_centre_id):
                results.append({"catalogId": catalog_id, "partNo": part_no, "success": False,
                                "error": "Cost centre confirmation required before allocation"})
                continue
            
            if job_id and section_id and cost_centre_id:
                # Job-allocated stock: 3-step CC move
                print(f"  Job-allocated: Job {job_id}, Section {section_id}, CC {cost_centre_id}")
                step_failed = False
                
                # Step 1: Un-assign from CC at source
                if source_id:
                    print(f"  Step 1: Un-assign from {source_name}")
                    try:
                        unassign_resp = simpro_request(
                            "PATCH",
                            f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cost_centre_id}/stock/{catalog_id}",
                            json={"AssignedBreakdown": [{"Storage": int(source_id), "Quantity": 0}]}
                        )
                        print(f"  Step 1: {unassign_resp.status_code}")
                        if unassign_resp.status_code not in (200, 204):
                            step_failed = True
                            results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": f"Un-assign failed: HTTP {unassign_resp.status_code}"})
                            continue
                    except Exception as e:
                        step_failed = True
                        results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": f"Un-assign error: {str(e)}"})
                        continue
                
                # Step 2: Stock transfer
                if not step_failed and source_id:
                    print(f"  Step 2: Transfer {source_name} -> {dest_name}")
                    try:
                        transfer_payload = {
                            "SourceStorageDeviceID": int(source_id),
                            "Items": [{
                                "CatalogID": int(catalog_id),
                                "DestinationStorageDeviceID": int(dest_id),
                                "Quantity": int(quantity)
                            }]
                        }
                        transfer_resp = simpro_request("POST", f"/companies/{COMPANY_ID}/stockTransfer/", json=transfer_payload)
                        print(f"  Step 2: {transfer_resp.status_code}")
                        if transfer_resp.status_code not in (200, 201, 204):
                            # Rollback step 1
                            print(f"  Step 2 FAILED - rolling back step 1")
                            try:
                                simpro_request("POST",
                                    f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cost_centre_id}/stock/",
                                    json={"Catalog": int(catalog_id), "AssignedBreakdown": [{"Storage": int(source_id), "Quantity": int(quantity)}]})
                            except:
                                pass
                            results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": f"Transfer failed: HTTP {transfer_resp.status_code}"})
                            continue
                    except Exception as e:
                        results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": f"Transfer error: {str(e)}"})
                        continue
                
                # Step 3: Re-assign to CC at destination
                print(f"  Step 3: Re-assign at {dest_name}")
                try:
                    reassign_resp = simpro_request(
                        "POST",
                        f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cost_centre_id}/stock/",
                        json={"Catalog": int(catalog_id), "AssignedBreakdown": [{"Storage": int(dest_id), "Quantity": int(quantity)}]}
                    )
                    print(f"  Step 3: {reassign_resp.status_code}")
                    if reassign_resp.status_code not in (200, 201, 204):
                        results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": f"Re-assign failed: HTTP {reassign_resp.status_code}"})
                        continue
                except Exception as e:
                    results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": f"Re-assign error: {str(e)}"})
                    continue
                
                results.append({"catalogId": catalog_id, "partNo": part_no, "success": True, "method": "job_3step"})
                success_count += 1
                print(f"  SUCCESS: {part_no} moved")
            elif target_job_id and not job_id:
                # General stock → allocate to target job
                print(f"  General stock → Job {target_job_id}")
                
                # Use confirmed section/CC from frontend CC confirmation step
                found_section = section_id
                found_cc = cost_centre_id
                
                if not found_section or not found_cc:
                    results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": "Missing confirmed cost centre for job allocation"})
                    continue
                
                # Step 2: Transfer stock from source to dest
                if source_id and str(source_id) != str(dest_id):
                    print(f"  Transfer: {source_name} -> {dest_name}")
                    try:
                        transfer_payload = {
                            "SourceStorageDeviceID": int(source_id),
                            "Items": [{
                                "CatalogID": int(catalog_id),
                                "DestinationStorageDeviceID": int(dest_id),
                                "Quantity": int(quantity)
                            }]
                        }
                        transfer_resp = simpro_request("POST", f"/companies/{COMPANY_ID}/stockTransfer/", json=transfer_payload)
                        print(f"  Transfer: {transfer_resp.status_code}")
                        if transfer_resp.status_code not in (200, 201, 204):
                            err_msg = f"Transfer failed: HTTP {transfer_resp.status_code}"
                            try:
                                err = transfer_resp.json()
                                if "Message" in err:
                                    err_msg = err["Message"]
                            except:
                                pass
                            results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": err_msg})
                            continue
                    except Exception as e:
                        results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": f"Transfer error: {str(e)}"})
                        continue
                
                # Step 3: Assign to job CC at destination
                print(f"  Assign to Job {target_job_id} CC {found_cc}")
                try:
                    assign_resp = simpro_request(
                        "POST",
                        f"/companies/{COMPANY_ID}/jobs/{target_job_id}/sections/{found_section}/costCenters/{found_cc}/stock/",
                        json={"Catalog": int(catalog_id), "AssignedBreakdown": [{"Storage": int(dest_id), "Quantity": int(quantity)}]}
                    )
                    print(f"  Assign: {assign_resp.status_code}")
                    if assign_resp.status_code in (200, 201, 204):
                        results.append({"catalogId": catalog_id, "partNo": part_no, "success": True, "method": "stock_to_job"})
                        success_count += 1
                        print(f"  SUCCESS: {part_no} allocated to Job {target_job_id}")
                    else:
                        err_msg = f"CC assign failed: HTTP {assign_resp.status_code}"
                        try:
                            err = assign_resp.json()
                            if "Message" in err:
                                err_msg = err["Message"]
                        except:
                            pass
                        results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": err_msg})
                except Exception as e:
                    results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": f"CC assign error: {str(e)}"})
            else:
                # Non-job stock: simple transfer
                if not source_id:
                    results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": "No source storage found"})
                    continue
                print(f"  General stock: simple transfer")
                try:
                    transfer_payload = {
                        "SourceStorageDeviceID": int(source_id),
                        "Items": [{
                            "CatalogID": int(catalog_id),
                            "DestinationStorageDeviceID": int(dest_id),
                            "Quantity": int(quantity)
                        }]
                    }
                    transfer_resp = simpro_request("POST", f"/companies/{COMPANY_ID}/stockTransfer/", json=transfer_payload)
                    if transfer_resp.status_code in (200, 201, 204):
                        results.append({"catalogId": catalog_id, "partNo": part_no, "success": True, "method": "simple_transfer"})
                        success_count += 1
                        print(f"  SUCCESS: {part_no} transferred")
                    else:
                        err_msg = f"Transfer failed: HTTP {transfer_resp.status_code}"
                        try:
                            err = transfer_resp.json()
                            if "Message" in err:
                                err_msg = err["Message"]
                        except:
                            pass
                        results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": err_msg})
                except Exception as e:
                    results.append({"catalogId": catalog_id, "partNo": part_no, "success": False, "error": str(e)})
        
        # Look up job info for response
        response_customer = customer_name
        response_job = job_number
        if target_job_id and not customer_name:
            try:
                job_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{target_job_id}?columns=ID,Name,Customer')
                if job_resp.status_code == 200:
                    jd = job_resp.json()
                    cust = jd.get('Customer', {})
                    if isinstance(cust, dict):
                        response_customer = cust.get('CompanyName', cust.get('GivenName', ''))
                    response_job = jd.get('Name', str(target_job_id))
            except:
                pass
        
        # Log the allocation
        try:
            db = get_db()
            for r in results:
                if r.get("success"):
                    orig = next((i for i in items if str(i.get("catalogId")) == str(r.get("catalogId"))), {})
                    db.execute("""INSERT INTO allocation_log 
                        (po_number, catalog_id, catalog_name, quantity, storage_location, staff_name, action_type, job_number, customer_name)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (orig.get("poOrderNo", "Stock"), str(r.get("catalogId")), r.get("partNo", ""),
                         orig.get("quantity", 1), dest_name, staff_name, "stock_allocation",
                         job_number, response_customer or customer_name))
            db.commit()
        except Exception as log_err:
            print(f"Allocation log error: {log_err}")
        
        return jsonify({
            "success": success_count > 0,
            "totalItems": len(items),
            "successCount": success_count,
            "failCount": len(items) - success_count,
            "results": results,
            "customerName": response_customer,
            "jobNumber": response_job
        })
    except Exception as e:
        print(f"Allocate from stock error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/stock-move', methods=['POST'])
@login_required
def stock_move():
    """Move stock between storage locations - handles job-allocated receipted items.
    
    3-step process for job-allocated stock:
    1. Un-assign from current storage in job cost centre
    2. Stock transfer to new storage device
    3. Re-assign to job cost centre at new storage
    
    For non-job stock: simple stock transfer only.
    """
    try:
        data = request.get_json()
        
        po_id = data.get('poId')
        source_id = data.get('sourceId')
        source_name = data.get('sourceName', 'Unknown')
        dest_id = data.get('destId')
        dest_name = data.get('destName', 'Unknown')
        items = data.get('items', [])
        staff_member = session.get('username', 'unknown')
        staff_name = session.get('display_name', staff_member)
        
        if not source_id or not dest_id or not items:
            return jsonify({'error': 'Missing required fields'}), 400
        
        if str(source_id) == str(dest_id):
            return jsonify({'error': 'Source and destination cannot be the same'}), 400
        
        print(f"=== STOCK MOVE REQUEST ===")
        print(f"PO: {po_id} | From: {source_name} (ID:{source_id}) -> To: {dest_name} (ID:{dest_id})")
        print(f"Items: {len(items)} | Staff: {staff_name}")
        
        success_count = 0
        results = []
        
        for item in items:
            catalog_id = item.get('catalogId')
            quantity = item.get('quantity', 1)
            part_no = item.get('partNo', '?')
            job_id = item.get('jobId')
            section_id = item.get('sectionId')
            cc_id = item.get('costCentreId')
            
            if not catalog_id:
                continue
            
            print(f"\n--- Moving {part_no} (Catalog:{catalog_id}) x{quantity} ---")
            
            # Auto-lookup section/CC if we have jobId but missing section/CC
            if job_id and (not section_id or not cc_id):
                print(f"  Auto-looking up section/CC for job {job_id}, catalog {catalog_id}")
                sec_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/')
                if sec_resp.status_code == 200:
                    for sec in sec_resp.json():
                        sid = sec.get('ID')
                        if not sid:
                            continue
                        cc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sid}/costCenters/')
                        if cc_resp.status_code == 200:
                            for cc in cc_resp.json():
                                ccid = cc.get('ID')
                                if not ccid:
                                    continue
                                stock_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sid}/costCenters/{ccid}/stock/{catalog_id}')
                                if stock_resp.status_code == 200:
                                    section_id = sid
                                    cc_id = ccid
                                    print(f"  Found: section={section_id}, cc={cc_id}")
                                    break
                            if section_id and cc_id:
                                break

            if job_id and section_id and cc_id:
                # Job-allocated stock: 3-step process
                print(f"Job-allocated: Job {job_id}, Section {section_id}, CC {cc_id}")
                
                # Step 1: Un-assign from current storage in job cost centre
                print(f"Step 1: Un-assign from {source_name}")
                unassign_payload = {
                    "AssignedBreakdown": [{"Storage": int(source_id), "Quantity": 0}]
                }
                unassign_resp = simpro_request(
                    'PATCH',
                    f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/{catalog_id}',
                    json=unassign_payload
                )
                print(f"Un-assign: {unassign_resp.status_code}")
                
                if unassign_resp.status_code not in (200, 204):
                    error_msg = f'Un-assign failed: {unassign_resp.status_code}'
                    try:
                        err = unassign_resp.json()
                        if 'errors' in err:
                            error_msg = err['errors'][0].get('message', error_msg)
                    except:
                        pass
                    results.append({'catalogId': catalog_id, 'partNo': part_no, 'success': False, 'error': error_msg, 'step': 'unassign'})
                    print(f"FAILED at Step 1: {error_msg}")
                    continue
                
                # Step 2: Stock transfer
                print(f"Step 2: Transfer {source_name} -> {dest_name}")
                transfer_payload = {
                    'SourceStorageDeviceID': int(source_id),
                    'Items': [{
                        'CatalogID': int(catalog_id),
                        'DestinationStorageDeviceID': int(dest_id),
                        'Quantity': int(quantity)
                    }]
                }
                transfer_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/stockTransfer/', json=transfer_payload)
                print(f"Transfer: {transfer_resp.status_code} - {transfer_resp.text[:200]}")
                
                if transfer_resp.status_code not in (200, 201, 204):
                    error_msg = f'Transfer failed: {transfer_resp.status_code}'
                    try:
                        err = transfer_resp.json()
                        if 'errors' in err:
                            error_msg = err['errors'][0].get('message', error_msg)
                    except:
                        pass
                    # Rollback: re-assign back to original storage
                    print(f"Transfer failed, rolling back: re-assign to {source_name}")
                    rollback = {
                        "Catalog": int(catalog_id),
                        "AssignedBreakdown": [{"Storage": int(source_id), "Quantity": int(quantity)}]
                    }
                    simpro_request('POST',
                        f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/',
                        json=rollback)
                    results.append({'catalogId': catalog_id, 'partNo': part_no, 'success': False, 'error': error_msg, 'step': 'transfer'})
                    print(f"FAILED at Step 2: {error_msg}")
                    continue
                
                # Step 3: Re-assign to job at new storage
                print(f"Step 3: Re-assign to job at {dest_name}")
                reassign_payload = {
                    "Catalog": int(catalog_id),
                    "AssignedBreakdown": [{"Storage": int(dest_id), "Quantity": int(quantity)}]
                }
                reassign_resp = simpro_request(
                    'POST',
                    f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/',
                    json=reassign_payload
                )
                print(f"Re-assign: {reassign_resp.status_code} - {reassign_resp.text[:200]}")
                
                if reassign_resp.status_code not in (200, 201, 204):
                    error_msg = f'Re-assign failed (stock transferred but not reassigned): {reassign_resp.status_code}'
                    try:
                        err = reassign_resp.json()
                        if 'errors' in err:
                            error_msg = err['errors'][0].get('message', error_msg)
                    except:
                        pass
                    results.append({'catalogId': catalog_id, 'partNo': part_no, 'success': False, 'error': error_msg, 'step': 'reassign'})
                    print(f"WARNING at Step 3: {error_msg}")
                    continue
                
                results.append({'catalogId': catalog_id, 'partNo': part_no, 'success': True, 'method': 'job_3step'})
                success_count += 1
                print(f"SUCCESS: {part_no} moved to {dest_name}")
                
            else:
                # Non-job stock: simple stock transfer
                print(f"General stock: simple transfer")
                transfer_payload = {
                    'SourceStorageDeviceID': int(source_id),
                    'Items': [{
                        'CatalogID': int(catalog_id),
                        'DestinationStorageDeviceID': int(dest_id),
                        'Quantity': int(quantity)
                    }]
                }
                transfer_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/stockTransfer/', json=transfer_payload)
                print(f"Transfer: {transfer_resp.status_code} - {transfer_resp.text[:200]}")
                
                if transfer_resp.status_code in (200, 201, 204):
                    results.append({'catalogId': catalog_id, 'partNo': part_no, 'success': True, 'method': 'simple_transfer'})
                    success_count += 1
                    print(f"SUCCESS: {part_no} moved to {dest_name}")
                else:
                    error_msg = f'Transfer failed: {transfer_resp.status_code}'
                    try:
                        err = transfer_resp.json()
                        if 'errors' in err:
                            error_msg = err['errors'][0].get('message', error_msg)
                    except:
                        pass
                    results.append({'catalogId': catalog_id, 'partNo': part_no, 'success': False, 'error': error_msg})
                    print(f"FAILED: {error_msg}")
        
        return jsonify({
            'successCount': success_count,
            'totalItems': len(items),
            'results': results,
            'movedBy': staff_name,
            'from': source_name,
            'to': dest_name
        })
        
    except Exception as e:
        print(f"Stock move error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


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
        
        # Build list of valid items to transfer
        transfer_items = []
        for item in items:
            catalog_id = item.get('catalogId')
            quantity = item.get('quantity', 1)
            if catalog_id:
                transfer_items.append({
                    'catalogId': int(catalog_id),
                    'quantity': int(quantity),
                    'partNo': item.get('partNo', ''),
                    'description': item.get('description', '')
                })
        
        if not transfer_items:
            return jsonify({'error': 'No valid items to transfer'}), 400
        
        print(f"=== STOCK TRANSFER REQUEST ===")
        print(f"From: {source_name} (ID: {source_id}) -> To: {dest_name} (ID: {dest_id})")
        print(f"Items: {len(transfer_items)}")
        
        # Execute stock transfers INDIVIDUALLY (Simpro has a documented batch bug — API Forum #2409)
        success_count = 0
        results = []
        
        for ti in transfer_items:
            payload = {
                'SourceStorageDeviceID': int(source_id),
                'Items': [{
                    'CatalogID': ti['catalogId'],
                    'DestinationStorageDeviceID': int(dest_id),
                    'Quantity': ti['quantity']
                }]
            }
            
            print(f"[TRANSFER] {ti['partNo']} x{ti['quantity']}: {source_name} -> {dest_name}")
            print(f"Payload: {json.dumps(payload)}")
            
            # POST to stockTransfer/ (singular — verified working endpoint)
            response = simpro_request('POST', f'/companies/{COMPANY_ID}/stockTransfer/', json=payload)
            
            print(f"Response: {response.status_code} - {response.text}")
            
            if response.status_code in (200, 201, 204):
                success_count += 1
                results.append({'catalogId': ti['catalogId'], 'success': True})
                print(f"Transfer SUCCESS: {ti['partNo']}")
            else:
                error_msg = f'API returned {response.status_code}'
                try:
                    err = response.json()
                    if isinstance(err, dict) and 'Message' in err:
                        error_msg = err['Message']
                except:
                    pass
                results.append({'catalogId': ti['catalogId'], 'success': False, 'error': error_msg})
                print(f"Transfer FAILED: {ti['partNo']} - {error_msg}")
        
        if success_count > 0:
            # Log the transfer
            staff_id = session.get('staff_id')
            log_allocation(
                staff_id=staff_id,
                staff_name=staff_name,
                po_number='',
                job_number='',
                vendor_name='',
                items_count=success_count,
                storage_location=f'{source_name} → {dest_name}',
                allocation_type='stock_transfer',
                verified=1
            )
            
            print(f"=== STOCK TRANSFER COMPLETE ===")
            print(f"Transferred {success_count}/{len(transfer_items)} item(s) from {source_name} to {dest_name}")
            
            return jsonify({
                'success': True,
                'message': f'Successfully transferred {success_count}/{len(transfer_items)} item(s) from {source_name} to {dest_name}',
                'transferredCount': success_count,
                'totalItems': len(transfer_items),
                'results': results,
                'transferredBy': staff_name
            })
        else:
            # All failed
            error_msgs = [r.get('error', 'Unknown') for r in results if not r.get('success')]
            error_summary = '; '.join(set(error_msgs)) if error_msgs else 'All transfers failed'
            
            print(f"=== STOCK TRANSFER FAILED ===")
            print(f"Error: {error_summary}")
            
            return jsonify({
                'success': False,
                'error': error_summary,
                'results': results
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
DAMAGE_WEBHOOK_URL = os.environ.get('DAMAGE_WEBHOOK_URL', 'https://webhooks.tasklet.ai/v1/public/webhook?token=4c824d3655353426e8c5114a2317ffa0')

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
                resolved_at = CURRENT_TIMESTAMP WHERE id = ?
        ''', (resolution, report_id))
        db.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================
# Version Endpoint (for deploy verification)
# ============================================

@app.route('/api/job-intel', methods=['POST'])
@login_required
def job_intel():
    """Get job stock intel - what's already received, what's pending, where it is"""
    try:
        data = request.json
        job_id = data.get('job_id')
        section_id = data.get('section_id')
        cost_center_id = data.get('cost_center_id')
        
        if not job_id:
            return jsonify({"error": "job_id required"}), 400
        
        token = get_simpro_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        base = SIMPRO_BASE_URL
        
        # 1. Get job details
        job_resp = requests.get(f"{base}/companies/{COMPANY_ID}/jobs/{job_id}", headers=headers)
        if job_resp.status_code != 200:
            return jsonify({"error": f"Job {job_id} not found"}), 404
        job = job_resp.json()
        
        job_info = {
            "id": job_id,
            "name": job.get("Name", ""),
            "customer": job.get("Customer", {}).get("CompanyName", ""),
            "site": job.get("Site", {}).get("Name", "")
        }
        
        # 2. Get sections (use provided or discover)
        if section_id:
            sections = [{"ID": int(section_id)}]
        else:
            sec_resp = requests.get(f"{base}/companies/{COMPANY_ID}/jobs/{job_id}/sections/", headers=headers)
            sections = sec_resp.json() if sec_resp.status_code == 200 else []
        
        # 3. For each section, get cost centers and stock
        all_stock = []
        cc_names = {}
        
        for section in sections:
            sec_id = section["ID"]
            
            if cost_center_id:
                ccs = [{"ID": int(cost_center_id), "Name": ""}]
            else:
                cc_resp = requests.get(f"{base}/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/", headers=headers)
                ccs = cc_resp.json() if cc_resp.status_code == 200 else []
            
            for cc in ccs:
                cc_id = cc["ID"]
                cc_name = cc.get("Name", "")
                cc_names[cc_id] = cc_name
                
                stock_resp = requests.get(f"{base}/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/{cc_id}/stock/", headers=headers)
                if stock_resp.status_code == 200:
                    stock_items = stock_resp.json()
                    for item in stock_items:
                        item["_cc_name"] = cc_name
                        item["_cc_id"] = cc_id
                        item["_section_id"] = sec_id
                        all_stock.append(item)
        
        # 4. Build response
        stock_list = []
        storage_map = {}  # storage_name -> list of items
        
        for s in all_stock:
            req_qty = s.get("Quantity", {}).get("Required", 0)
            assigned_qty = s.get("Quantity", {}).get("Assigned", 0)
            
            if req_qty == 0 and assigned_qty == 0:
                continue
            
            # Track storage locations where this item sits
            item_storage = []
            for breakdown in s.get("AssignedBreakdown", []):
                qty = breakdown.get("Quantity", 0)
                if qty > 0:
                    storage_name = breakdown.get("Storage", {}).get("Name", "Unknown")
                    storage_id = breakdown.get("Storage", {}).get("ID", 0)
                    item_storage.append({"name": storage_name, "id": storage_id, "qty": qty})
                    
                    if storage_name not in storage_map:
                        storage_map[storage_name] = {"name": storage_name, "id": storage_id, "items": []}
                    storage_map[storage_name]["items"].append({
                        "name": s["Catalog"]["Name"],
                        "partNo": s["Catalog"].get("PartNo", ""),
                        "qty": qty
                    })
            
            stock_list.append({
                "name": s["Catalog"]["Name"],
                "partNo": s["Catalog"].get("PartNo", ""),
                "required": req_qty,
                "assigned": assigned_qty,
                "pending": max(0, req_qty - assigned_qty),
                "costCenter": s.get("_cc_name", ""),
                "storageLocations": item_storage
            })
        
        total_required = sum(s["required"] for s in stock_list)
        total_assigned = sum(s["assigned"] for s in stock_list)
        
        return jsonify({
            "job": job_info,
            "stock": stock_list,
            "summary": {
                "totalItems": len(stock_list),
                "totalRequired": total_required,
                "totalAssigned": total_assigned,
                "totalPending": max(0, total_required - total_assigned),
                "isComplete": total_assigned >= total_required and total_required > 0
            },
            "storageLocations": list(storage_map.values())
        })
        
    except Exception as e:
        print(f"Job intel error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/version')
def get_version():
    return jsonify({'version': '2026-04-19-stock-transfer-fix', 'status': 'ok'})

# ============================================
# Test Label PDF Endpoint
# ============================================
@app.route('/api/test-label-pdf')
def test_label_pdf():
    """Generate a test label PDF for QL-810W printer (DK-2225 38mm tape)"""
    try:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.pdfbase.pdfmetrics import stringWidth
        
        # DK-2225: 38mm wide continuous tape
        page_w, page_h = 38*mm, 200*mm  # Portrait orientation confirmed working
        margin = 3*mm
        avail_w = page_h - 2*margin  # 194mm usable width (along tape length)
        avail_h = page_w - 2*margin  # 32mm usable height
        
        # Test data
        line1 = "Job 12345 \u00b7 Test Customer Name"
        line2 = "ABC-1234 \u00b7 Test Catalog Item Description Here"
        line3 = "Qty: 10 \u00b7 Van Stock (George) \u00b7 17/04/2026 \u00b7 PO 21100"
        
        def auto_fit_font(text, font_name, max_size, max_width):
            """Find the largest font size that fits within max_width"""
            size = max_size
            while size > 5:
                w = stringWidth(text, font_name, size)
                if w <= max_width:
                    return size
                size -= 0.5
            return 5
        
        # Calculate auto-fit font sizes (start big, scale down to fit)
        size1 = auto_fit_font(line1, "Helvetica-Bold", 18, avail_w)
        size2 = auto_fit_font(line2, "Helvetica", 14, avail_w)
        size3 = auto_fit_font(line3, "Helvetica", 12, avail_w)
        
        buf = io.BytesIO()
        c = pdf_canvas.Canvas(buf, pagesize=(page_w, page_h))
        
        # Rotate for portrait label (text reads along tape length)
        c.saveState()
        c.translate(0, 0)
        c.rotate(90)
        
        # After rotation: drawing space is 200mm wide x 38mm tall
        # Y coordinates are negative (rotated coordinate system)
        # Distribute 3 lines evenly across 32mm height
        line_spacing = avail_h / 3
        y_base = -page_w + margin
        
        # Line 1 (top) - bold job info
        c.setFont("Helvetica-Bold", size1)
        c.drawString(margin, y_base + 2*line_spacing + 2*mm, line1)
        
        # Line 2 (middle) - catalog info
        c.setFont("Helvetica", size2)
        c.drawString(margin, y_base + line_spacing + 1*mm, line2)
        
        # Line 3 (bottom) - details
        c.setFont("Helvetica", size3)
        c.drawString(margin, y_base + 1*mm, line3)
        
        c.restoreState()
        c.save()
        buf.seek(0)
        
        return send_file(
            buf,
            mimetype='application/pdf',
            as_attachment=False,
            download_name='test-label.pdf'
        )
    except ImportError:
        return jsonify({'error': 'reportlab not installed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# Dynamic Label PDF Endpoint (for PO items)
# ============================================
@app.route('/api/label-pdf', methods=['POST'])
@login_required
def generate_label_pdf():
    """Generate label PDF(s) for QL-810W printer. Accepts single or multiple labels."""
    try:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.pdfbase.pdfmetrics import stringWidth
        
        data = request.get_json()
        
        # Support both single label and array of labels
        labels = data.get('labels', None)
        if labels is None:
            # Single label format (backward compatible)
            labels = [{
                'line1': data.get('jobInfo', 'Unknown Job'),
                'line2': data.get('catalogInfo', 'Unknown Item'),
                'line3': data.get('detailInfo', '')
            }]
        
        if not labels:
            return jsonify({'error': 'No labels provided'}), 400
        
        page_w, page_h = 38*mm, 200*mm
        margin = 3*mm
        avail_w = page_h - 2*margin
        avail_h = page_w - 2*margin
        
        def auto_fit_font(text, font_name, max_size, max_width):
            size = max_size
            while size > 5:
                w = stringWidth(text, font_name, size)
                if w <= max_width:
                    return size
                size -= 0.5
            return 5
        
        buf = io.BytesIO()
        c = pdf_canvas.Canvas(buf, pagesize=(page_w, page_h))
        
        for idx, label in enumerate(labels):
            if idx > 0:
                c.showPage()
            
            l1 = str(label.get('line1', ''))
            l2 = str(label.get('line2', ''))
            l3 = str(label.get('line3', ''))
            label_type = label.get('type', 'item')
            
            if label_type == 'filing':
                # Compact filing label - 28mm long, all bold, for sticking on paperwork
                filing_h = 28*mm
                c.setPageSize((page_w, filing_h))
                filing_avail_w = filing_h - 2*margin  # 22mm text width
                filing_avail_h = page_w - 2*margin     # 32mm text height
                
                size1 = auto_fit_font(l1, "Helvetica-Bold", 12, filing_avail_w)
                size2 = auto_fit_font(l2, "Helvetica-Bold", 10, filing_avail_w)
                size3 = auto_fit_font(l3, "Helvetica-Bold", 9, filing_avail_w)
                
                c.saveState()
                c.rotate(90)
                
                line_spacing = filing_avail_h / 3
                y_base = -page_w + margin
                
                # Draw a thin border to make it visually distinct
                c.setStrokeColorRGB(0.3, 0.3, 0.3)
                c.setLineWidth(0.5)
                c.rect(margin, y_base, filing_avail_w, filing_avail_h)
                
                c.setFont("Helvetica-Bold", size1)
                c.drawString(margin + 1*mm, y_base + 2*line_spacing + 0.5*mm, l1)
                c.setFont("Helvetica-Bold", size2)
                c.drawString(margin + 1*mm, y_base + line_spacing + 0.5*mm, l2)
                c.setFont("Helvetica-Bold", size3)
                c.drawString(margin + 1*mm, y_base + 0.5*mm, l3)
                
                c.restoreState()
                # Reset page size for any subsequent labels
                c.setPageSize((page_w, page_h))
            else:
                # Standard item label
                size1 = auto_fit_font(l1, "Helvetica-Bold", 18, avail_w)
                size2 = auto_fit_font(l2, "Helvetica", 14, avail_w)
                size3 = auto_fit_font(l3, "Helvetica", 12, avail_w)
                
                c.saveState()
                c.rotate(90)
                
                line_spacing = avail_h / 3
                y_base = -page_w + margin
                
                c.setFont("Helvetica-Bold", size1)
                c.drawString(margin, y_base + 2*line_spacing + 2*mm, l1)
                c.setFont("Helvetica", size2)
                c.drawString(margin, y_base + line_spacing + 1*mm, l2)
                c.setFont("Helvetica", size3)
                c.drawString(margin, y_base + 1*mm, l3)
                
                c.restoreState()
        
        c.save()
        buf.seek(0)
        
        return send_file(
            buf,
            mimetype='application/pdf',
            as_attachment=False,
            download_name='labels.pdf'
        )
    except ImportError:
        return jsonify({'error': 'reportlab not installed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# Damage Report Endpoints
# ============================================
@app.route('/api/report-damage', methods=['POST'])
@login_required
def report_damage():
    """Receive damage report from app user and forward to Tasklet webhook"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        po_number = data.get('po_number', '')
        po_id = data.get('po_id', '')
        catalog_id = data.get('catalog_id', '')
        item_description = data.get('item_description', '')
        part_number = data.get('part_number', '')
        quantity_damaged = data.get('quantity_damaged', 1)
        notes = data.get('notes', '').strip()
        photos_base64 = data.get('photos', [])
        vendor_name = data.get('vendor_name', '')
        vendor_id = data.get('vendor_id', '')
        job_number = data.get('job_number', '')
        customer_name = data.get('customer_name', '')
        
        if not item_description:
            return jsonify({'error': 'Item description is required'}), 400
        
        report_id = str(uuid.uuid4())[:8]
        staff_user = session.get('username', 'unknown')
        staff_name = session.get('display_name', 'Unknown')
        
        db = get_db()
        db.execute('''
            INSERT INTO damage_reports (id, po_number, po_id, catalog_id, item_description,
                part_number, quantity_damaged, notes, photo_count, photos_base64,
                vendor_name, vendor_id, job_number, customer_name,
                staff_user, staff_name, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
        ''', (report_id, po_number, po_id, catalog_id, item_description,
              part_number, quantity_damaged, notes,
              len(photos_base64), json.dumps(photos_base64),
              vendor_name, vendor_id, job_number, customer_name,
              staff_user, staff_name))
        db.commit()
        
        print(f"=== DAMAGE REPORT {report_id} ===")
        print(f"Staff: {staff_name} ({staff_user})")
        print(f"PO: {po_number}, Item: {item_description}")
        print(f"Part: {part_number}, Qty damaged: {quantity_damaged}")
        print(f"Vendor: {vendor_name}, Job: {job_number}, Customer: {customer_name}")
        print(f"Notes: {notes}")
        print(f"Photos: {len(photos_base64)}")
        
        if DAMAGE_WEBHOOK_URL:
            try:
                webhook_payload = {
                    'type': 'damage_report',
                    'report_id': report_id,
                    'po_number': po_number,
                    'po_id': po_id,
                    'catalog_id': catalog_id,
                    'item_description': item_description,
                    'part_number': part_number,
                    'quantity_damaged': quantity_damaged,
                    'notes': notes,
                    'photo_count': len(photos_base64),
                    'vendor_name': vendor_name,
                    'vendor_id': vendor_id,
                    'job_number': job_number,
                    'customer_name': customer_name,
                    'staff_user': staff_user,
                    'staff_name': staff_name,
                    'timestamp': datetime.now().isoformat()
                }
                resp = requests.post(DAMAGE_WEBHOOK_URL, json=webhook_payload, timeout=10)
                print(f"Damage webhook sent: {resp.status_code}")
            except Exception as e:
                print(f"Damage webhook failed (report still saved): {e}")
        else:
            print("WARNING: DAMAGE_WEBHOOK_URL not set - report saved but not forwarded")
        
        return jsonify({
            'success': True,
            'report_id': report_id,
            'message': 'Damage reported! Supplier and customer will be notified.'
        })
        
    except Exception as e:
        print(f"Error saving damage report: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/damage-reports', methods=['GET'])
@login_required
def list_damage_reports():
    """List damage reports"""
    try:
        status = request.args.get('status', None)
        po_number = request.args.get('po_number', None)
        db = get_db()
        
        query = '''SELECT id, po_number, item_description, part_number, quantity_damaged,
                    notes, photo_count, vendor_name, job_number, customer_name,
                    staff_user, staff_name, status, created_at, resolved_at
                FROM damage_reports'''
        conditions = []
        params = []
        
        if status:
            conditions.append('status = ?')
            params.append(status)
        if po_number:
            conditions.append('po_number = ?')
            params.append(po_number)
        
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        query += ' ORDER BY created_at DESC'
        
        reports = db.execute(query, tuple(params)).fetchall()
        return jsonify({'reports': [dict(r) for r in reports], 'count': len(reports)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/damage-reports/<report_id>', methods=['GET'])
def get_damage_report(report_id):
    """Fetch a damage report by ID (for Tasklet email processing)"""
    try:
        db = get_db()
        report = db.execute('SELECT * FROM damage_reports WHERE id = ?', (report_id,)).fetchone()
        if not report:
            return jsonify({'error': 'Report not found'}), 404
        
        result = dict(report)
        if result.get('photos_base64'):
            result['photos'] = json.loads(result['photos_base64'])
        else:
            result['photos'] = []
        del result['photos_base64']
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/damage-reports/<report_id>/resolve', methods=['POST'])
@login_required
def resolve_damage_report(report_id):
    """Mark a damage report as resolved"""
    try:
        data = request.get_json() or {}
        resolution = data.get('resolution', '')
        
        db = get_db()
        if USE_PG:
            db.execute('UPDATE damage_reports SET status = %s, resolved_at = NOW() WHERE id = %s',
                       ('resolved', report_id))
        else:
            db.execute("UPDATE damage_reports SET status = 'resolved', resolved_at = datetime('now') WHERE id = ?",
                       (report_id,))
        db.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@app.route('/api/job-cc-lookup', methods=['POST'])
@login_required
def job_cc_lookup():
    """Look up job details and matching cost centres for a catalog item.
    No AI - pure string/ID matching only."""
    try:
        data = request.get_json()
        job_id = data.get('jobId')
        catalog_id = data.get('catalogId')
        part_no = (data.get('partNo') or '').strip().lower()
        description = (data.get('description') or '').strip().lower()

        if not job_id:
            return jsonify({'error': 'jobId is required'}), 400
        if not catalog_id and not part_no and not description:
            return jsonify({'error': 'At least one of catalogId, partNo, or description is required'}), 400

        # Get job details
        job_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}?columns=ID,Name,Customer,Site')
        if job_resp.status_code != 200:
            return jsonify({'error': f'Job not found: HTTP {job_resp.status_code}'}), 400
        
        jd = job_resp.json()
        cust = jd.get('Customer', {})
        customer_name = ''
        if isinstance(cust, dict):
            customer_name = cust.get('CompanyName') or cust.get('GivenName', '')
        site = jd.get('Site', {})
        site_address = ''
        if isinstance(site, dict):
            addr = site.get('Address', {})
            if isinstance(addr, dict):
                parts = [addr.get('Line1', ''), addr.get('City', ''), addr.get('State', '')]
                site_address = ', '.join(p for p in parts if p)
            elif isinstance(site, dict):
                site_address = site.get('Name', '')

        job_info = {
            'id': job_id,
            'name': jd.get('Name', str(job_id)),
            'customer': customer_name,
            'site': site_address
        }

        # Get all sections
        sec_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/')
        if sec_resp.status_code != 200:
            return jsonify({'job': job_info, 'matches': [], 'notFound': True})

        matches = []

        for sec in sec_resp.json():
            sid = sec.get('ID')
            section_name = sec.get('Name', f'Section {sid}')
            if not sid:
                continue

            cc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sid}/costCenters/')
            if cc_resp.status_code != 200:
                continue

            for cc in cc_resp.json():
                ccid = cc.get('ID')
                cc_name = cc.get('Name', f'Cost Centre {ccid}')
                if not ccid:
                    continue

                # Get stock items on this CC
                stock_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sid}/costCenters/{ccid}/stock/')
                if stock_resp.status_code != 200:
                    continue

                stock_items = stock_resp.json()
                if not isinstance(stock_items, list):
                    stock_items = []

                for stock_item in stock_items:
                    item_catalog_id = stock_item.get('Catalog', {})
                    if isinstance(item_catalog_id, dict):
                        item_catalog_id = item_catalog_id.get('ID')
                    
                    item_part_no = (stock_item.get('PartNo') or stock_item.get('Catalog', {}).get('PartNo', '') if isinstance(stock_item.get('Catalog'), dict) else '').strip().lower()
                    item_desc = (stock_item.get('Name') or stock_item.get('Catalog', {}).get('Name', '') if isinstance(stock_item.get('Catalog'), dict) else '').strip().lower()

                    # Match logic: primary catalogId, secondary partNo, tertiary description
                    matched = False
                    if catalog_id and item_catalog_id and str(item_catalog_id) == str(catalog_id):
                        matched = True
                    elif part_no and item_part_no and item_part_no == part_no:
                        matched = True
                    elif description and item_desc and item_desc == description:
                        matched = True

                    if matched:
                        required_qty = stock_item.get('Quantity', 0) or 0
                        assigned_qty = stock_item.get('AssignedQuantity', 0) or 0
                        remaining_qty = max(0, required_qty - assigned_qty)

                        # Get storage locations
                        storage_locs = []
                        breakdown = stock_item.get('AssignedBreakdown', [])
                        if isinstance(breakdown, list):
                            for b in breakdown:
                                storage_id = b.get('Storage')
                                if isinstance(storage_id, dict):
                                    storage_id = storage_id.get('ID')
                                storage_name = b.get('StorageName', '')
                                if not storage_name and isinstance(b.get('Storage'), dict):
                                    storage_name = b['Storage'].get('Name', '')
                                qty = b.get('Quantity', 0)
                                if storage_id and qty:
                                    storage_locs.append({'id': storage_id, 'name': storage_name, 'qty': qty})

                        matches.append({
                            'sectionId': sid,
                            'sectionName': section_name,
                            'costCentreId': ccid,
                            'costCentreName': cc_name,
                            'catalogId': item_catalog_id,
                            'description': stock_item.get('Name') or (stock_item.get('Catalog', {}).get('Name', '') if isinstance(stock_item.get('Catalog'), dict) else ''),
                            'partNo': stock_item.get('PartNo') or (stock_item.get('Catalog', {}).get('PartNo', '') if isinstance(stock_item.get('Catalog'), dict) else ''),
                            'requiredQty': required_qty,
                            'assignedQty': assigned_qty,
                            'remainingQty': remaining_qty,
                            'storageLocations': storage_locs
                        })

        not_found = len(matches) == 0
        return jsonify({'job': job_info, 'matches': matches, 'notFound': not_found})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/job-note', methods=['POST'])
@login_required
def job_note():
    """Add a note to a job in Simpro."""
    try:
        data = request.get_json()
        job_id = data.get('jobId')
        note = data.get('note', '')

        if not job_id or not note:
            return jsonify({'error': 'jobId and note are required'}), 400

        note_resp = simpro_request('POST', f'/companies/{COMPANY_ID}/jobs/{job_id}/notes/',
                                   json={'Description': note})
        if note_resp.status_code in (200, 201):
            return jsonify({'success': True})
        else:
            return jsonify({'error': f'Failed to add note: HTTP {note_resp.status_code}'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

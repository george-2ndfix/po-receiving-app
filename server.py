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

# PostgreSQL support
try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

DATABASE_URL = os.environ.get('DATABASE_URL')
# Fix Render's postgres:// to postgresql://
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

USE_POSTGRES = bool(DATABASE_URL and HAS_PSYCOPG)
import uuid
import concurrent.futures

# ============ STOCK CACHE (v106) ============
import threading

_stock_cache = {}        # {catalog_id: [{storageId, storageName, availableQty}]}
_stock_cache_lock = threading.Lock()
_stock_cache_built_at = 0  # timestamp
_stock_cache_ttl = 300     # 5 minutes
_stock_cache_building = False

def _build_stock_cache():
    """Scan all storage devices and build full stock index. ~40 sec first time."""
    global _stock_cache, _stock_cache_built_at, _stock_cache_building
    import time as _time
    
    _stock_cache_building = True
    print("[stock-cache] Building stock cache...")
    start = _time.time()
    
    try:
        token = get_simpro_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        # Get all storage devices
        storage_resp = requests.get(
            f"{SIMPRO_BASE_URL}/companies/{COMPANY_ID}/storageDevices/?pageSize=250",
            headers=headers, timeout=15
        )
        if storage_resp.status_code != 200:
            print(f"[stock-cache] Failed to get storage devices: {storage_resp.status_code}")
            _stock_cache_building = False
            return
        
        all_storage = storage_resp.json()
        if not isinstance(all_storage, list):
            all_storage = []
        
        SKIP_NAMES = {"Delivered to Site", "On Site", "Customer Collected", "PICK UP FROM SUPPLIER", "Delivery by Supplier"}
        physical_storage = [d for d in all_storage if d.get("Name", "") not in SKIP_NAMES]
        
        new_cache = {}
        
        def fetch_device_stock(device):
            dev_id = device.get("ID")
            dev_name = device.get("Name", f"Storage {dev_id}")
            if not dev_id:
                return []
            try:
                t = get_simpro_token()
                all_items = []
                page = 1
                while True:
                    url = f"{SIMPRO_BASE_URL}/companies/{COMPANY_ID}/storageDevices/{dev_id}/stock/?pageSize=250&page={page}"
                    resp = requests.get(url, headers={"Authorization": f"Bearer {t}"}, timeout=15)
                    if resp.status_code != 200:
                        break
                    items = resp.json()
                    if not isinstance(items, list) or not items:
                        break
                    all_items.extend(items)
                    if len(items) < 250:
                        break
                    page += 1
                results = []
                for s in all_items:
                    cat = s.get("Catalog", {})
                    c_id = cat.get("ID")
                    if c_id:
                        qty = s.get("InventoryCount", 0) or s.get("Quantity", 0) or 0
                        if isinstance(qty, dict):
                            qty = qty.get("Available", 0) or qty.get("Quantity", 0) or 0
                        if qty and qty > 0:
                            results.append({"catalogId": c_id, "storageId": dev_id, "storageName": dev_name, "availableQty": qty})
                return results
            except Exception as e:
                print(f"[stock-cache] Error fetching device {dev_id}: {e}")
                return []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            futures = {executor.submit(fetch_device_stock, dev): dev for dev in physical_storage}
            for future in concurrent.futures.as_completed(futures, timeout=120):
                try:
                    results = future.result(timeout=15)
                    for r in results:
                        cid = r["catalogId"]
                        if cid not in new_cache:
                            new_cache[cid] = []
                        new_cache[cid].append({
                            "storageId": r["storageId"],
                            "storageName": r["storageName"],
                            "availableQty": r["availableQty"]
                        })
                except Exception as e:
                    print(f"[stock-cache] Future error: {e}")
        
        with _stock_cache_lock:
            _stock_cache = new_cache
            _stock_cache_built_at = _time.time()
        
        elapsed = _time.time() - start
        total_items = sum(len(v) for v in new_cache.values())
        print(f"[stock-cache] Cache built in {elapsed:.1f}s - {len(new_cache)} catalog items across {total_items} locations")
        
    except Exception as e:
        print(f"[stock-cache] Error building cache: {e}")
    finally:
        _stock_cache_building = False


def _get_stock_cache():
    """Get the stock cache, rebuilding if expired or empty."""
    import time as _time
    global _stock_cache_built_at
    
    now = _time.time()
    if now - _stock_cache_built_at > _stock_cache_ttl or not _stock_cache:
        _build_stock_cache()
    
    with _stock_cache_lock:
        # Return a deep copy so callers dont mutate the cache
        import copy
        return copy.deepcopy(_stock_cache)


def _deduct_from_cache(catalog_id, storage_id, quantity):
    """Deduct quantity from cache after allocation. Updates in-place."""
    with _stock_cache_lock:
        if catalog_id in _stock_cache:
            for loc in _stock_cache[catalog_id]:
                if loc["storageId"] == storage_id:
                    loc["availableQty"] = max(0, loc["availableQty"] - quantity)
                    if loc["availableQty"] == 0:
                        _stock_cache[catalog_id].remove(loc)
                    print(f"[stock-cache] Deducted {quantity} of catalog {catalog_id} from storage {storage_id}, remaining: {loc.get('availableQty', 0)}")
                    return
        print(f"[stock-cache] Warning: catalog {catalog_id} / storage {storage_id} not found in cache")


_inv_cache = {}          # {catalog_id: [{storageId, storageName, availableQty}]}
_inv_cache_lock = threading.Lock()
_inv_cache_built_at = {}  # {catalog_id: timestamp}
_inv_cache_ttl = 300      # 5 minutes

def _lookup_stock_for_items(catalog_ids):
    """Fast stock lookup using /catalogs/{id}/inventories/ endpoint.
    Returns dict: {catalog_id: [{storageId, storageName, availableQty}]}
    Uses per-item cache with 5-min TTL.
    """
    import time as _time
    start = _time.time()
    result = {}
    now = _time.time()

    # Check cache first — return cached items, only query uncached/expired ones
    uncached_ids = []
    with _inv_cache_lock:
        for cat_id in catalog_ids:
            if cat_id in _inv_cache and cat_id in _inv_cache_built_at:
                if now - _inv_cache_built_at[cat_id] < _inv_cache_ttl:
                    if _inv_cache[cat_id]:
                        result[cat_id] = [loc.copy() for loc in _inv_cache[cat_id]]
                    continue
            uncached_ids.append(cat_id)

    if not uncached_ids:
        elapsed = _time.time() - start
        print(f"[inv-lookup] All {len(catalog_ids)} items from cache in {elapsed:.1f}s")
        return result

    print(f"[inv-lookup] {len(catalog_ids) - len(uncached_ids)} from cache, {len(uncached_ids)} to query")

    SKIP_NAMES = {"Delivered to Site", "On Site", "Customer Collected", "PICK UP FROM SUPPLIER", "Delivery by Supplier"}

    # Get token ONCE and share across all threads
    shared_token = get_simpro_token()

    def lookup_single_item(cat_id):
        """Look up all storage locations + quantities for one catalog item."""
        try:
            headers = {"Authorization": f"Bearer {shared_token}"}

            # Step 1: Get list of storage devices for this item
            list_resp = requests.get(
                f"{SIMPRO_BASE_URL}/companies/{COMPANY_ID}/catalogs/{cat_id}/inventories/",
                headers=headers, timeout=15
            )
            if list_resp.status_code != 200:
                print(f"[inv-lookup] List failed for catalog {cat_id}: {list_resp.status_code}")
                return cat_id, []

            devices = list_resp.json()
            if not isinstance(devices, list):
                return cat_id, []

            # Filter out non-physical storage
            physical = [d for d in devices if d.get("StorageDevice", {}).get("Name", "") not in SKIP_NAMES]

            # Step 2: Get detail (with InventoryCount) for each device — parallel
            locations = []

            def get_device_detail(device_info):
                sd = device_info.get("StorageDevice", {})
                sd_id = sd.get("ID")
                sd_name = sd.get("Name", f"Storage {sd_id}")
                if not sd_id:
                    return None
                try:
                    h = {"Authorization": f"Bearer {shared_token}"}
                    r = requests.get(
                        f"{SIMPRO_BASE_URL}/companies/{COMPANY_ID}/catalogs/{cat_id}/inventories/{sd_id}",
                        headers=h, timeout=10
                    )
                    if r.status_code == 200:
                        data = r.json()
                        qty = data.get("InventoryCount", 0)
                        if qty and qty > 0:
                            return {"storageId": sd_id, "storageName": sd_name, "availableQty": qty}
                    # Fallback: inventories detail returns 0 for pre-build/one-off items
                    # Check storage device stock endpoint directly
                    r2 = requests.get(
                        f"{SIMPRO_BASE_URL}/companies/{COMPANY_ID}/storageDevices/{sd_id}/stock/?Catalog.ID={cat_id}&pageSize=5",
                        headers=h, timeout=10
                    )
                    if r2.status_code == 200:
                        for st in r2.json():
                            ic = st.get("InventoryCount", 0)
                            if ic and ic > 0:
                                return {"storageId": sd_id, "storageName": sd_name, "availableQty": ic}
                except Exception as e:
                    print(f"[inv-lookup] Detail error cat={cat_id} dev={sd_id}: {e}")
                return None

            # Use threads for parallel detail calls (limit to 5 to avoid Simpro rate limits)
            checked_device_ids = set(d.get("StorageDevice", {}).get("ID") for d in physical)
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as detail_exec:
                detail_futures = [detail_exec.submit(get_device_detail, d) for d in physical]
                for f in concurrent.futures.as_completed(detail_futures, timeout=30):
                    try:
                        loc = f.result(timeout=10)
                        if loc:
                            locations.append(loc)
                    except:
                        pass

            # If no stock found, check extra common storage devices not in inventories list
            # Simpro bug: inventories list can be incomplete for pre-build/one-off items
            if not locations:
                EXTRA_DEVICES = [
                    (149, "Back Room"), (153, "Reception"), (38, "Stock Holding"),
                    (69, "Shed"), (4, "Customer Cupboard"), (21, "Builders Cupboard"),
                    (219, "Boardroom"), (260, "Hall - Entrance"), (52, "Stock - Seal Room"),
                    (67, "Stock Shelves"), (146, "Showroom Display"),
                ]
                extra = [{"StorageDevice": {"ID": did, "Name": dn}} for did, dn in EXTRA_DEVICES if did not in checked_device_ids]
                if extra:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as extra_exec:
                        extra_futures = [extra_exec.submit(get_device_detail, d) for d in extra]
                        for f in concurrent.futures.as_completed(extra_futures, timeout=20):
                            try:
                                loc = f.result(timeout=10)
                                if loc:
                                    locations.append(loc)
                            except:
                                pass

            return cat_id, locations
        except Exception as e:
            print(f"[inv-lookup] Error for catalog {cat_id}: {e}")
            return cat_id, []

    # Parallel lookup for uncached catalog items (limit to 3 to avoid Simpro rate limits)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(lookup_single_item, cid) for cid in uncached_ids]
        for future in concurrent.futures.as_completed(futures, timeout=120):
            try:
                cat_id, locations = future.result(timeout=30)
                # Cache regardless of whether we found stock
                with _inv_cache_lock:
                    _inv_cache[cat_id] = locations
                    _inv_cache_built_at[cat_id] = _time.time()
                if locations:
                    result[cat_id] = locations
            except Exception as e:
                print(f"[inv-lookup] Future error: {e}")

    elapsed = _time.time() - start
    total_locs = sum(len(v) for v in result.values())
    print(f"[inv-lookup] Looked up {len(catalog_ids)} items in {elapsed:.1f}s — {len(result)} have stock across {total_locs} locations")
    return result


# ============ END STOCK CACHE ============
import re
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, send_file, session
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
class PostgresCursorWrapper:
    """Wraps psycopg cursor to translate ? placeholders to %s"""
    def __init__(self, cursor):
        self._cursor = cursor
    
    def execute(self, query, params=None):
        # Convert SQLite ? placeholders to PostgreSQL %s
        query = query.replace('?', '%s')
        # Convert SQLite datetime('now') to PostgreSQL NOW()
        query = query.replace("datetime('now')", "NOW()")
        if params:
            return self._cursor.execute(query, params)
        return self._cursor.execute(query)
    
    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        # Return a dict-like object that supports both dict access and index access
        return DictRow(row)
    
    def fetchall(self):
        rows = self._cursor.fetchall()
        return [DictRow(row) for row in rows]
    
    @property
    def rowcount(self):
        return self._cursor.rowcount
    
    @property
    def lastrowid(self):
        # PostgreSQL doesn't have lastrowid - not used in this app
        return None
    
    @property 
    def description(self):
        return self._cursor.description


class DictRow:
    """Makes psycopg dict rows work like sqlite3.Row (supports both index and key access)"""
    def __init__(self, data):
        if isinstance(data, dict):
            self._data = data
            self._keys = list(data.keys())
        else:
            self._data = dict(data) if hasattr(data, 'keys') else {}
            self._keys = list(self._data.keys())
    
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[self._keys[key]]
        return self._data[key]
    
    def __contains__(self, key):
        return key in self._data
    
    def keys(self):
        return self._keys
    
    def get(self, key, default=None):
        return self._data.get(key, default)
    
    def __repr__(self):
        return repr(self._data)


class PostgresConnectionWrapper:
    """Wraps psycopg connection to behave like sqlite3 connection"""
    def __init__(self, conn):
        self._conn = conn
    
    def cursor(self):
        return PostgresCursorWrapper(self._conn.cursor())
    
    def execute(self, query, params=None):
        """Proxy execute to cursor for SQLite compatibility"""
        cursor = self.cursor()
        cursor.execute(query, params)
        return cursor
    
    def commit(self):
        self._conn.commit()
    
    def close(self):
        self._conn.close()
    
    def rollback(self):
        self._conn.rollback()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


def get_db():
    """Get database connection - PostgreSQL if available, SQLite fallback"""
    if USE_POSTGRES:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
        return PostgresConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    """Initialize database tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    if USE_POSTGRES:
        # PostgreSQL DDL
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS staff (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'staff',
                email TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS allocation_logs (
                id SERIAL PRIMARY KEY,
                staff_id INTEGER NOT NULL,
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
        ''')
        
        cursor.execute('''
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
                resolved_at TEXT
            )
        ''')
        
        cursor.execute('''
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
        ''')
        
        cursor.execute('''
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
                created_at TIMESTAMP DEFAULT NOW(),
                resolved_at TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS damage_reports (
                id SERIAL PRIMARY KEY,
                po_id TEXT,
                po_number TEXT,
                catalog_id INTEGER,
                part_number TEXT,
                description TEXT,
                quantity_damaged INTEGER,
                damage_notes TEXT,
                photo_count INTEGER DEFAULT 0,
                photos_base64 TEXT,
                staff_id INTEGER,
                staff_name TEXT,
                vendor_name TEXT,
                job_number TEXT,
                customer_name TEXT,
                notification_sent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_relocations (
                id SERIAL PRIMARY KEY,
                po_id TEXT NOT NULL,
                catalog_id INTEGER NOT NULL,
                part_number TEXT,
                description TEXT,
                quantity INTEGER NOT NULL,
                source_storage_id INTEGER,
                source_storage_name TEXT,
                dest_storage_id INTEGER,
                dest_storage_name TEXT,
                job_id TEXT,
                job_number TEXT,
                section_id TEXT,
                cost_center_id TEXT,
                status TEXT DEFAULT 'pending',
                staff_id INTEGER,
                staff_name TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collections (
                id SERIAL PRIMARY KEY,
                job_number VARCHAR(50) NOT NULL,
                job_id INTEGER,
                job_name VARCHAR(255),
                customer_name VARCHAR(255),
                customer_email VARCHAR(255),
                customer_phone VARCHAR(100),
                site_address TEXT,
                collected_by VARCHAR(255) NOT NULL,
                staff_id INTEGER NOT NULL,
                staff_name VARCHAR(100),
                signature_data TEXT,
                notes TEXT,
                vehicle_rego VARCHAR(50),
                status VARCHAR(50) DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collection_items (
                id SERIAL PRIMARY KEY,
                collection_id INTEGER NOT NULL REFERENCES collections(id),
                catalog_id INTEGER,
                part_code VARCHAR(100),
                description TEXT,
                quantity INTEGER NOT NULL,
                storage_location VARCHAR(255),
                storage_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collection_photos (
                id SERIAL PRIMARY KEY,
                collection_id INTEGER NOT NULL REFERENCES collections(id),
                photo_data TEXT NOT NULL,
                caption VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        
        print("PostgreSQL tables initialized")
    else:
        # SQLite DDL (existing code)
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
        if USE_POSTGRES:
            conn.rollback()  # PostgreSQL requires rollback after failed ALTER
    
    # Seed staff accounts
    staff_seed = [
        ('george', 'George', 'admin', '2ndFix5082', 'george@2ndfix.com.au'),
        ('jim', 'Jim', 'manager', '2ndFix5082', 'jim@2ndfix.com.au'),
        ('cherie', 'Cherie', 'manager', '2ndFix5082', None),
        ('tom', 'Tom', 'manager', '2ndFix5082', 'tom@2ndfix.com.au'),
        ('tyrese', 'Tyrese', 'staff', 'Tyrese123', None),
        ('mik', 'Mik', 'staff', '2ndFix5082', None),
        ('ryan', 'Ryan', 'staff', '2ndFix5082', None),
        ('kelly', 'Kelly', 'admin', '2ndFix5082', 'info@kpro.net.au'),
    ]
    
    for username, display_name, role, password, email in staff_seed:
        cursor.execute("SELECT COUNT(*) FROM staff WHERE username = ?", (username,))
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute('''
                INSERT INTO staff (username, display_name, password_hash, role, active, email)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (username, display_name, hash_password(password), role, 1, email))
            print(f"Created staff account: {username} ({role})")
        else:
            cursor.execute('UPDATE staff SET password_hash = ? WHERE username = ?',
                          (hash_password(password), username))
            print(f"Reset password for {username}")
            if email:
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


@app.route('/api/label-pdf', methods=['POST'])
@login_required
def label_pdf():
    """Generate label PDF for QL-810W printer - DK-2225 38mm tape.
    Uses 38mm-wide page (matching tape) with text rotated 90 degrees.
    This is the proven approach that works correctly with the QL-810W."""
    try:
        data = request.get_json()
        if not data or ('items' not in data and 'labels' not in data):
            return jsonify({'error': 'Missing items or labels'}), 400
        
        use_preformatted = 'labels' in data
        items = data.get('labels', data.get('items', []))
        po_number = data.get('poNumber', 'N/A')
        job_number = data.get('jobNumber', '')
        customer_name = data.get('customerName', '')
        today = datetime.now().strftime('%d/%m/%Y')
        
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.pdfbase.pdfmetrics import stringWidth
        
        PAGE_W = 38 * mm          # tape width (fixed - matches DK-2225)
        ITEM_LENGTH = 120 * mm    # item label length along tape
        MARGIN = 3 * mm
        MIN_FILING_LEN = 50 * mm
        MAX_FILING_LEN = 120 * mm
        
        def auto_fit_font(text, font_name, max_size, max_width):
            size = max_size
            while size > 5:
                w = stringWidth(text, font_name, size)
                if w <= max_width:
                    return size
                size -= 0.5
            return 5
        
        def wrap_text(text, font_name, font_size, max_w):
            words = text.split()
            lines_out, current = [], ""
            for word in words:
                test = f"{current} {word}".strip()
                if stringWidth(test, font_name, font_size) <= max_w:
                    current = test
                else:
                    if current:
                        lines_out.append(current)
                    current = word
            if current:
                lines_out.append(current)
            return lines_out if lines_out else [""]
        
        def calc_filing_length(texts_fonts):
            max_w = 0
            for text, fn, fs in texts_fonts:
                w = stringWidth(text, fn, fs)
                if w > max_w:
                    max_w = w
            return min(MAX_FILING_LEN, max(MIN_FILING_LEN, max_w + MARGIN * 2 + 2*mm))
        
        buf = io.BytesIO()
        c = pdf_canvas.Canvas(buf)
        
        for label_item in items:
            label_type = label_item.get('type', 'item') if use_preformatted else 'item'
            
            # Skip filing labels in main loop (handled after)
            if label_type == 'filing':
                continue
            
            if use_preformatted:
                l1 = str(label_item.get('line1', ''))
                l2_raw = str(label_item.get('line2', ''))
                l3 = str(label_item.get('line3', ''))
                # Split line2 into bold part code + regular description
                if ' \u00b7 ' in l2_raw:
                    part_code, desc = l2_raw.split(' \u00b7 ', 1)
                else:
                    part_code = l2_raw
                    desc = ''
            else:
                part_no_raw = label_item.get('partNo', '')
                desc = label_item.get('description', '')
                qty = label_item.get('quantity', 0)
                storage = label_item.get('storageLocation', '')
                item_job = label_item.get('jobNumber', job_number)
                item_customer = label_item.get('customerName', customer_name)
                
                l1 = f"Job {item_job}  {item_customer}" if item_job else item_customer
                part_code = part_no_raw
                bottom_parts = [f"Qty: {qty}"]
                if storage:
                    bottom_parts.append(storage)
                bottom_parts.append(today)
                bottom_parts.append(f"PO {po_number}")
                l3 = "    ".join(bottom_parts)
            
            # Item label: 38mm wide (tape) x 120mm long
            c.setPageSize((PAGE_W, ITEM_LENGTH))
            avail_w = ITEM_LENGTH - 2 * MARGIN  # text width along tape
            avail_h = PAGE_W - 2 * MARGIN       # text height across tape (32mm)
            
            # Font sizes
            s1 = auto_fit_font(l1, "Helvetica-Bold", 14, avail_w)
            s_part = auto_fit_font(part_code, "Helvetica-Bold", 12, avail_w)
            s3 = auto_fit_font(l3, "Helvetica", 10, avail_w)
            
            # Check if description fits inline after part code
            part_w = stringWidth(part_code + "  ", "Helvetica-Bold", s_part)
            desc_avail = avail_w - part_w
            desc_inline = desc and stringWidth(desc, "Helvetica", 9) <= desc_avail
            
            if desc and not desc_inline:
                desc_wrapped = wrap_text(desc, "Helvetica", 9, avail_w)
            else:
                desc_wrapped = []
            
            # Calculate vertical layout (in mm)
            line_heights = [s1 * 0.3528, s_part * 0.3528, s3 * 0.3528]
            extra_desc = len(desc_wrapped) * 4 if desc_wrapped else 0
            gap = 2.5
            total_h = line_heights[0] + gap + line_heights[1] + extra_desc + gap + line_heights[2]
            
            # Center vertically in available height
            top_offset = ((avail_h / mm) - total_h) / 2
            
            c.saveState()
            c.rotate(90)
            
            # After rotate(90): x = along tape, y = -(across tape)
            y_start = -PAGE_W + MARGIN + avail_h - top_offset * mm
            y = y_start
            
            # Line 1: Job + Customer (bold)
            c.setFont("Helvetica-Bold", s1)
            y -= line_heights[0] * mm
            c.drawString(MARGIN, y, l1)
            
            # Line 2: Part code (bold) + optional inline description
            y -= gap * mm
            c.setFont("Helvetica-Bold", s_part)
            y -= line_heights[1] * mm
            c.drawString(MARGIN, y, part_code)
            
            if desc_inline and desc:
                c.setFont("Helvetica", 9)
                c.drawString(MARGIN + part_w, y, desc)
            elif desc_wrapped:
                c.setFont("Helvetica", 9)
                for dl in desc_wrapped:
                    y -= 4 * mm
                    c.drawString(MARGIN, y, dl)
            
            # Line 3: Qty, Location, Date, PO
            y -= gap * mm
            c.setFont("Helvetica", s3)
            y -= line_heights[2] * mm
            c.drawString(MARGIN, y, l3)
            
            c.restoreState()
            c.showPage()
        
        # Filing label
        filing_label = None
        if use_preformatted:
            for fi in data.get('labels', []):
                if fi.get('type') == 'filing':
                    filing_label = fi
                    break
            # Extract metadata from first label if needed
            if not job_number:
                for lbl in data.get('labels', []):
                    if lbl.get('type') != 'filing':
                        ll1 = lbl.get('line1', '')
                        if 'Job ' in ll1:
                            for p in ll1.replace(' \u00b7 ', '|').split('|'):
                                p = p.strip()
                                if p.startswith('Job '):
                                    job_number = p.replace('Job ', '')
                                elif p and not customer_name:
                                    customer_name = p
                        ll3 = lbl.get('line3', '')
                        if 'PO ' in ll3:
                            for seg in ll3.replace(' \u00b7 ', '|').split('|'):
                                seg = seg.strip()
                                if seg.startswith('PO '):
                                    po_number = seg.replace('PO ', '')
                        break
        
        if filing_label:
            fl1 = filing_label.get('line1', '')
            fl2 = filing_label.get('line2', '')
            fl3 = filing_label.get('line3', '')
        elif job_number:
            storage_loc = items[0].get('storageLocation', '') if items else ''
            fl1 = f"Job {job_number}  PO {po_number}"
            fl2 = customer_name
            fl3 = f"Storage: {storage_loc}  {today}" if storage_loc else today
        else:
            fl1 = None
        
        if fl1:
            filing_len = calc_filing_length([
                (fl1, "Helvetica-Bold", 14),
                (fl2, "Helvetica-Bold", 11),
                (fl3, "Helvetica-Bold", 10),
            ])
            c.setPageSize((PAGE_W, filing_len))
            
            f_avail_w = filing_len - 2 * MARGIN
            f_avail_h = PAGE_W - 2 * MARGIN
            
            fs1 = auto_fit_font(fl1, "Helvetica-Bold", 14, f_avail_w)
            fs2 = auto_fit_font(fl2, "Helvetica-Bold", 11, f_avail_w)
            fs3 = auto_fit_font(fl3, "Helvetica-Bold", 10, f_avail_w)
            
            c.saveState()
            c.rotate(90)
            
            y_base = -PAGE_W + MARGIN
            line_spacing = f_avail_h / 3
            
            c.setStrokeColorRGB(0.3, 0.3, 0.3)
            c.setLineWidth(0.5)
            c.rect(MARGIN, y_base, f_avail_w, f_avail_h)
            
            c.setFont("Helvetica-Bold", fs1)
            c.drawString(MARGIN + 1*mm, y_base + 2*line_spacing + 0.5*mm, fl1)
            c.setFont("Helvetica-Bold", fs2)
            c.drawString(MARGIN + 1*mm, y_base + line_spacing + 0.5*mm, fl2)
            c.setFont("Helvetica-Bold", fs3)
            c.drawString(MARGIN + 1*mm, y_base + 0.5*mm, fl3)
            
            c.restoreState()
            c.showPage()
        
        c.save()
        buf.seek(0)
        
        return send_file(
            buf,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f'labels_PO_{po_number}.pdf'
        )
    except Exception as e:
        print(f"[{datetime.now()}] Label PDF error: {e}")
        return jsonify({'error': str(e)}), 500

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
    """Get storage locations from Simpro API (cached 10 min)"""
    return get_storage_devices_cached()

_storage_devices_cache = {"data": None, "time": 0}

def get_storage_devices_cached():
    """Fetch all storage devices from Simpro with 10-minute cache"""
    import time as _time
    now = _time.time()
    if _storage_devices_cache["data"] and (now - _storage_devices_cache["time"]) < 600:
        return jsonify(_storage_devices_cache["data"])
    try:
        resp = simpro_request('GET', f'/companies/{COMPANY_ID}/storageDevices/?pageSize=250')
        if resp.status_code != 200:
            return jsonify({'error': f'Simpro API error: {resp.status_code}'}), 500
        devices = resp.json()
        result = [{"id": d["ID"], "name": d.get("Name", f"Device {d['ID']}")} for d in devices]
        result.sort(key=lambda x: x["name"])
        _storage_devices_cache["data"] = result
        _storage_devices_cache["time"] = now
        return jsonify(result)
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


# ============================================
# Merged PO Detection & Auto-Correction
# ============================================

def get_po_merge_mapping(po_id):
    """
    Reads audit logs to detect merged POs and trace each item back to its original job/CC.
    Returns: {catalog_id: {"job": "5600", "section": "31512", "cc": "31512", "original_po": "21227"}} 
    or empty dict if not a merged PO.
    """
    import re
    
    # Step 1: Get audit logs for this PO
    resp = simpro_request('GET', f'/companies/{COMPANY_ID}/logs/vendorOrders/?VendorOrderID={po_id}')
    if resp.status_code != 200:
        print(f"Merge check: Could not get logs for PO {po_id}: {resp.status_code}")
        return {}
    
    logs = resp.json()
    
    # Step 2: Find "Merged in PO #XXXXX" entries
    merged_po_numbers = []
    for log in logs:
        msg = log.get('Message', '')
        match = re.search(r'Merged in PO #(\d+)', msg)
        if match:
            merged_po_numbers.append(match.group(1))
    
    if not merged_po_numbers:
        print(f"Merge check: PO {po_id} is not a merged PO")
        return {}
    
    print(f"Merge check: PO {po_id} has {len(merged_po_numbers)} merged POs: {merged_po_numbers}")
    
    # Step 3: Get the host PO's original job/CC from its "Created purchase order" log
    host_job = None
    host_cc = None
    host_items = []
    for log in logs:
        msg = log.get('Message', '')
        create_match = re.search(r'Created purchase order.*with job no\. (\d+)-(\d+)', msg)
        if create_match:
            host_job = create_match.group(1)
            host_cc = create_match.group(2)
        if 'Added Item:' in msg and log.get('CatalogID'):
            # Items added before any merge are host PO items
            host_items.append(log['CatalogID'])
    
    # Build mapping - start with empty
    catalog_to_job = {}
    
    # Step 4: For each merged PO, get its logs to find its job/CC and items
    for merged_po in merged_po_numbers:
        m_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/logs/vendorOrders/?VendorOrderID={merged_po}')
        if m_resp.status_code != 200:
            print(f"  Could not get logs for merged PO {merged_po}: {m_resp.status_code}")
            continue
        
        m_logs = m_resp.json()
        m_job = None
        m_cc = None
        m_items = []
        
        for log in m_logs:
            msg = log.get('Message', '')
            create_match = re.search(r'Created purchase order.*with job no\. (\d+)-(\d+)', msg)
            if create_match:
                m_job = create_match.group(1)
                m_cc = create_match.group(2)
            if 'Added Item:' in msg and log.get('CatalogID'):
                m_items.append(log['CatalogID'])
        
        if m_job and m_cc:
            print(f"  Merged PO {merged_po}: Job {m_job}, CC {m_cc}, Items: {m_items}")
            # Look up the section ID for this job
            section_id = get_section_for_job(m_job, m_cc)
            for cat_id in m_items:
                catalog_to_job[cat_id] = {
                    'job': m_job,
                    'cc': m_cc,
                    'section': section_id,
                    'original_po': merged_po
                }
        else:
            print(f"  Merged PO {merged_po}: Could not determine job/CC")
    
    print(f"Merge mapping complete: {len(catalog_to_job)} items mapped to non-host jobs")
    return catalog_to_job


def get_section_for_job(job_number, cc_id):
    """Look up the section ID for a job's cost centre."""
    resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/?ID={job_number}')
    if resp.status_code == 200:
        jobs = resp.json()
        if jobs:
            job_id = jobs[0]['ID']
            sec_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/')
            if sec_resp.status_code == 200:
                sections = sec_resp.json()
                for section in sections:
                    sec_id = section['ID']
                    cc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/')
                    if cc_resp.status_code == 200:
                        for cc in cc_resp.json():
                            if str(cc['ID']) == str(cc_id):
                                return str(sec_id)
    return None


def correct_merged_po_allocations(po_id, host_job, host_section, host_cc, storage_device_id, allocated_items):
    """
    After receipt, check if PO is merged and move items to their correct job CCs.
    allocated_items: list of {catalog_id, quantity} that were just allocated.
    Returns list of corrections made.
    """
    merge_map = get_po_merge_mapping(po_id)
    if not merge_map:
        return []  # Not a merged PO, nothing to do
    
    corrections = []
    
    for item in allocated_items:
        catalog_id = item.get('catalog_id')
        qty = item.get('quantity', 1)
        
        if catalog_id not in merge_map:
            continue  # This item belongs to the host PO's job - no move needed
        
        target = merge_map[catalog_id]
        target_job = target['job']
        target_cc = target['cc']
        target_section = target.get('section')
        
        if not target_section:
            print(f"  SKIP catalog {catalog_id}: could not find section for Job {target_job} CC {target_cc}")
            corrections.append({'catalog_id': catalog_id, 'status': 'error', 'reason': 'section_not_found'})
            continue
        
        print(f"  MOVING catalog {catalog_id} (qty {qty}): Job {host_job} CC {host_cc} -> Job {target_job} CC {target_cc}")
        
        try:
            # Step 1: Un-assign from host job CC
            unassign_url = f'/companies/{COMPANY_ID}/jobs/{host_job}/sections/{host_section}/costCenters/{host_cc}/stock/{catalog_id}/'
            unassign_resp = simpro_request('PATCH', unassign_url, json={
                "AssignedBreakdown": [{"Storage": int(storage_device_id), "Quantity": 0}]
            })
            print(f"    Step 1 un-assign: {unassign_resp.status_code}")
            
            if unassign_resp.status_code not in (200, 204):
                print(f"    Un-assign failed: {unassign_resp.text[:200]}")
                corrections.append({'catalog_id': catalog_id, 'status': 'error', 'reason': f'unassign_failed_{unassign_resp.status_code}'})
                continue
            
            # Step 2: Re-assign to correct job CC (no transfer needed - same storage device)
            reassign_url = f'/companies/{COMPANY_ID}/jobs/{target_job}/sections/{target_section}/costCenters/{target_cc}/stock/'
            reassign_resp = simpro_request('POST', reassign_url, json={
                "Catalog": catalog_id,
                "AssignedBreakdown": [{"Storage": int(storage_device_id), "Quantity": qty}]
            })
            print(f"    Step 2 re-assign to Job {target_job}: {reassign_resp.status_code}")
            
            if reassign_resp.status_code in (200, 201):
                print(f"    OK: catalog {catalog_id} moved to Job {target_job}")
                corrections.append({
                    'catalog_id': catalog_id, 
                    'status': 'success',
                    'from_job': host_job,
                    'to_job': target_job,
                    'to_cc': target_cc
                })
            else:
                print(f"    Re-assign failed: {reassign_resp.text[:200]}")
                # Rollback: re-assign back to host
                rollback_url = f'/companies/{COMPANY_ID}/jobs/{host_job}/sections/{host_section}/costCenters/{host_cc}/stock/'
                simpro_request('POST', rollback_url, json={
                    "Catalog": catalog_id,
                    "AssignedBreakdown": [{"Storage": int(storage_device_id), "Quantity": qty}]
                })
                corrections.append({'catalog_id': catalog_id, 'status': 'error', 'reason': f'reassign_failed_{reassign_resp.status_code}'})
        
        except Exception as e:
            print(f"    Error moving catalog {catalog_id}: {e}")
            corrections.append({'catalog_id': catalog_id, 'status': 'error', 'reason': str(e)})
    
    return corrections



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
        
        po_number = data.get('poNumber', po_id)  # Define early - used in error logging
        
        if not po_id or not items or not storage_device_id:
            return jsonify({'error': 'Missing required fields'}), 400
        
        STOCK_HOLDING_ID = 3  # Stock Holding device ID
        
        results = []
        success_count = 0
        fail_count = 0
        
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
                                    assigned_to = alloc.get('AssignedTo', {})
                                    receipt_allocations[cat_id] = {
                                        'storage_id': sd_id,
                                        'storage_name': sd_name,
                                        'quantity': alloc.get('Quantity', 0),
                                        'cc_job': assigned_to.get('Job'),
                                        'cc_section': assigned_to.get('Section'),
                                        'cc_id': assigned_to.get('CostCenter', {}).get('ID') if isinstance(assigned_to.get('CostCenter'), dict) else assigned_to.get('CostCenter'),
                                        'cc_name': assigned_to.get('CostCenter', {}).get('Name', '') if isinstance(assigned_to.get('CostCenter'), dict) else ''
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
            # Per-item receipt check: item is only receipted if it actually appears on a receipt
            # (not just because the PO has ANY receipt — receipts may only cover some items)
            item_is_on_receipt = catalog_id in receipt_allocations or catalog_id in catalog_receipt_id
            is_receipted = item_is_on_receipt or receipt_status == 'fully_receipted'
            
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
                    # Pass CC assignment info for 3-step transfer (CC-allocated stock is invisible to storageDevices endpoint)
                    cc_data = receipt_allocations.get(catalog_id, {})
                    if cc_data.get('cc_job'):
                        item['cc_job'] = cc_data['cc_job']
                        item['cc_section'] = cc_data['cc_section']
                        item['cc_id'] = cc_data['cc_id']
                        item['cc_name'] = cc_data.get('cc_name', '')
                    post_receipt_items.append(item)
                    print(f"Catalog {catalog_id}: In Stock at {current_storage_name}, CC={cc_data.get('cc_name','none')}, using stock transfer to {storage_device_id}")
                else:
                    # Receipt EXISTS but ItemsReceived NOT ticked = "In Transit"
                    # CRITICAL: Do NOT use pre-receipt PUT - it doubles cost centre entries!
                    # Instead: tick ItemsReceived on the receipt first, then stock transfer
                    r_id = catalog_receipt_id.get(catalog_id)
                    if r_id:
                        try:
                            print(f"Catalog {catalog_id}: In Transit - ticking ItemsReceived on receipt {r_id}...")
                            patch_resp = simpro_request('PATCH', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/receipts/{r_id}', json={'ItemsReceived': True})
                            print(f"ItemsReceived PATCH response: {patch_resp.status_code} - {patch_resp.text}")
                            if patch_resp.status_code in (200, 204):
                                print(f"✅ ItemsReceived set to true for receipt {r_id}")
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
                    # Try to tick ItemsReceived on the first receipt
                    r_id = catalog_receipt_id.get(catalog_id)
                    if r_id:
                        try:
                            print(f"Catalog {catalog_id}: No alloc data, ticking ItemsReceived on receipt {r_id}...")
                            patch_resp = simpro_request('PATCH', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/receipts/{r_id}', json={'ItemsReceived': True})
                            print(f"ItemsReceived PATCH response: {patch_resp.status_code}")
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
            
            # Fetch existing allocations — MUST preserve AssignedTo and multi-job splits!
            # PUT replaces ALL allocations, so we must include every existing entry with its AssignedTo.
            # Only change StorageDevice. Without this, multi-job POs collapse to one job.
            existing_allocs = []
            try:
                existing_resp = simpro_request('GET', allocation_url)
                if existing_resp.status_code == 200:
                    existing_allocs = existing_resp.json()
                    print(f"[PRE-RECEIPT] Existing allocations for catalog {catalog_id}: {len(existing_allocs)} entries")
                    for ea in existing_allocs:
                        ea_assigned = ea.get('AssignedTo', {})
                        ea_job = ea_assigned.get('Job', '?') if isinstance(ea_assigned, dict) else '?'
                        ea_qty = ea.get('Quantity', {})
                        ea_total = ea_qty.get('Total', 0) if isinstance(ea_qty, dict) else ea_qty
                        print(f"  Existing: Job={ea_job}, Qty={ea_total}, AssignedTo.ID={ea_assigned.get('ID','?') if isinstance(ea_assigned, dict) else '?'}")
            except Exception as ae:
                print(f"[PRE-RECEIPT] Error fetching existing allocations: {ae}")
            
            # Build payload preserving existing job splits
            if existing_allocs and len(existing_allocs) > 0:
                # Preserve EVERY existing allocation entry — just update StorageDevice
                payload = []
                for existing_alloc in existing_allocs:
                    ea_qty = existing_alloc.get('Quantity', {})
                    ea_total = ea_qty.get('Total', 0) if isinstance(ea_qty, dict) else (ea_qty if isinstance(ea_qty, (int, float)) else 0)
                    if ea_total <= 0:
                        ea_total = int(quantity)
                    
                    entry = {
                        'StorageDevice': int(storage_device_id),
                        'Quantity': int(ea_total)
                    }
                    # CRITICAL: Preserve AssignedTo to maintain job/CC assignment
                    ea_assigned = existing_alloc.get('AssignedTo', {})
                    if isinstance(ea_assigned, dict) and ea_assigned.get('ID'):
                        entry['AssignedTo'] = ea_assigned['ID']
                        print(f"  Preserving AssignedTo={ea_assigned['ID']} (Job {ea_assigned.get('Job','?')})")
                    payload.append(entry)
                print(f"[PRE-RECEIPT] Preserved {len(payload)} allocation entries with job splits")
            else:
                # No existing allocations — simple single allocation
                payload = [{
                    'StorageDevice': int(storage_device_id),
                    'Quantity': int(quantity)
                }]
            
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
                                # Check if item has CC assignment — CC-allocated stock is invisible to storageDevices endpoint
                                if item.get('cc_job') and item.get('cc_id'):
                                    print(f"📦 {part_no}: 0 free stock in {source_name} BUT CC-allocated (Job {item['cc_job']}, CC {item['cc_id']}) — will use 3-step transfer")
                                    item['needs_cc_unassign'] = True
                                else:
                                    print(f"⏭️ Skipping {part_no} ({desc}): 0 stock in {source_name}")
                                    results.append({
                                        'catalogId': catalog_id,
                                        'success': False,
                                        'quantity': quantity,
                                        'method': 'skipped_zero_stock',
                                        'error': f'No stock available in {source_name} - item may not have arrived yet'
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
                
                # Transfer items one-by-one using flat format (Simpro batch bug workaround)
                print(f"[POST-RECEIPT] Stock Transfer from {source_name} (ID:{source_id}) to {storage_name}")
                all_transferred = True
                for item in group_items:
                    catalog_id = item.get('catalogId')
                    quantity = item.get('quantity', 1)
                    if quantity <= 0:
                        quantity = 1
                    
                    # 3-STEP PROCESS for CC-allocated stock (Known Conflict #13 + #1)
                    # CC-allocated stock is invisible to storageDevices AND can't be transferred directly
                    if item.get('needs_cc_unassign'):
                        cc_job = item['cc_job']
                        cc_section = item['cc_section']
                        cc_id = item['cc_id']
                        print(f"  🔄 3-step transfer for {catalog_id}: un-assign from CC (Job {cc_job}, Section {cc_section}, CC {cc_id})")
                        
                        # Step 1: Un-assign from CC at source storage
                        try:
                            unassign_resp = simpro_request('PATCH', 
                                f'/companies/{COMPANY_ID}/jobs/{cc_job}/sections/{cc_section}/costCenters/{cc_id}/stock/{catalog_id}/',
                                json={'AssignedBreakdown': [{'Storage': int(source_id), 'Quantity': 0}]})
                            print(f"  Step 1 (un-assign): {unassign_resp.status_code} - {unassign_resp.text[:200]}")
                            if unassign_resp.status_code not in (200, 204):
                                print(f"  ❌ Un-assign failed — skipping this item")
                                results.append({
                                    'catalogId': catalog_id,
                                    'success': False,
                                    'quantity': quantity,
                                    'method': 'cc_unassign_failed',
                                    'error': f'Failed to un-assign from CC: {unassign_resp.status_code}'
                                })
                                continue
                        except Exception as ua_err:
                            print(f"  ❌ Un-assign error: {ua_err}")
                            results.append({
                                'catalogId': catalog_id,
                                'success': False,
                                'quantity': quantity,
                                'method': 'cc_unassign_error',
                                'error': f'Un-assign error: {str(ua_err)}'
                            })
                            continue
                        
                        # Brief pause for Simpro to process
                        import time
                        time.sleep(1)
                    
                    transfer_payload = {
                        'Catalog': int(catalog_id),
                        'FromStorage': int(source_id),
                        'ToStorage': int(storage_device_id),
                        'Quantity': int(quantity)
                    }
                    print(f"  Transfer payload: {json.dumps(transfer_payload)}")
                    transfer_response = simpro_request('POST', f'/companies/{COMPANY_ID}/stockTransfer/', json=transfer_payload)
                    print(f"  Response: {transfer_response.status_code} - {transfer_response.text[:200]}")
                    if transfer_response.status_code in (200, 201, 204):
                        # Step 3 (if CC-allocated): Re-assign to CC at destination
                        if item.get('needs_cc_unassign'):
                            cc_job = item['cc_job']
                            cc_section = item['cc_section']
                            cc_id = item['cc_id']
                            try:
                                reassign_resp = simpro_request('POST',
                                    f'/companies/{COMPANY_ID}/jobs/{cc_job}/sections/{cc_section}/costCenters/{cc_id}/stock/',
                                    json={'Catalog': int(catalog_id), 'AssignedBreakdown': [{'Storage': int(storage_device_id), 'Quantity': int(quantity)}]})
                                print(f"  Step 3 (re-assign): {reassign_resp.status_code} - {reassign_resp.text[:200]}")
                                if reassign_resp.status_code in (200, 201, 204):
                                    print(f"  ✅ 3-step complete: CC re-assigned at {storage_name}")
                                else:
                                    print(f"  ⚠️ Re-assign returned {reassign_resp.status_code} — stock transferred but CC not updated")
                            except Exception as ra_err:
                                print(f"  ⚠️ Re-assign error: {ra_err} — stock transferred but CC not updated")
                        
                        results.append({
                            'catalogId': catalog_id,
                            'success': True,
                            'quantity': quantity,
                            'verified': True,
                            'method': 'stock_transfer',
                            'message': f'Transferred from {source_name} to {storage_name}'
                        })
                        success_count += 1
                    else:
                        all_transferred = False
                        results.append({
                            'catalogId': catalog_id,
                            'success': False,
                            'quantity': quantity,
                            'error': f'Transfer failed: {transfer_response.status_code} - {transfer_response.text[:200]}',
                            'method': 'stock_transfer'
                        })
                        fail_count += 1
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
                            'Catalog': int(catalog_id),
                            'FromStorage': int(source_id),
                            'ToStorage': int(storage_device_id),
                            'Quantity': int(quantity)
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
        # Merged PO auto-correction
        # If this PO absorbed other POs, move items to their correct job CCs
        # ============================================
        merge_corrections = []
        if success_count > 0:
            try:
                # Build list of successfully allocated items
                allocated_items_for_merge = []
                for r in results:
                    if r.get('success') and r.get('catalogId'):
                        allocated_items_for_merge.append({
                            'catalog_id': r['catalogId'],
                            'quantity': r.get('quantity', 1)
                        })
                
                if allocated_items_for_merge:
                    # Get host job info from PO
                    po_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/')
                    if po_resp.status_code == 200:
                        po_data_full = po_resp.json()
                        host_job_id = None
                        host_section_id = None
                        host_cc_id = None
                        
                        # Extract job/section/CC from PO data
                        job_info = po_data_full.get('Job', {})
                        if job_info:
                            host_job_id = str(job_info.get('ID', ''))
                        
                        if host_job_id:
                            # Look up section and CC
                            sec_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{host_job_id}/sections/')
                            if sec_resp.status_code == 200:
                                for sec in sec_resp.json():
                                    sec_id = sec['ID']
                                    cc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{host_job_id}/sections/{sec_id}/costCenters/')
                                    if cc_resp.status_code == 200:
                                        for cc in cc_resp.json():
                                            host_section_id = str(sec_id)
                                            host_cc_id = str(cc['ID'])
                                            break
                                    if host_cc_id:
                                        break
                        
                        if host_job_id and host_section_id and host_cc_id:
                            print(f"=== MERGE CHECK: PO {po_id}, Host Job {host_job_id}, Section {host_section_id}, CC {host_cc_id} ===")
                            merge_corrections = correct_merged_po_allocations(
                                po_id, host_job_id, host_section_id, host_cc_id,
                                storage_device_id, allocated_items_for_merge
                            )
                            if merge_corrections:
                                moved = [c for c in merge_corrections if c['status'] == 'success']
                                failed = [c for c in merge_corrections if c['status'] == 'error']
                                print(f"=== MERGE CORRECTIONS: {len(moved)} moved, {len(failed)} failed ===")
                        else:
                            print(f"Merge check: Could not determine host job info for PO {po_id}")
                    else:
                        print(f"Merge check: Could not fetch PO {po_id}: {po_resp.status_code}")
            except Exception as merge_err:
                print(f"Merge correction error (non-fatal): {merge_err}")
                import traceback
                traceback.print_exc()
        
        # ============================================
        # Set PO status based on whether ALL items are now received
        # 239 = Goods Received (all items done) — triggers Kelly's KPro to receipt & archive
        # 109 = Not Completely Supplied (partial delivery) — keeps PO open for remaining items
        # ============================================
        goods_received_set = False
        if success_count > 0 and pre_receipt_items:
            try:
                # Check if ALL PO items were ticked by the user
                # NOTE: Simpro Received counter only updates when Kelly receipts — NOT when we allocate
                # So we compare items the user ticked (in this request) vs total items on the PO
                cat_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}/catalogs/')
                all_received = False  # Default to partial (safe)
                if cat_resp.status_code == 200:
                    po_items = cat_resp.json()
                    total_po_items = len(po_items)
                    items_being_allocated = len(items)  # items user ticked in this request
                    
                    if items_being_allocated >= total_po_items:
                        all_received = True
                        print(f"All {total_po_items} items ticked by user — full delivery → 239")
                    else:
                        all_received = False
                        print(f"Partial: user ticked {items_being_allocated}/{total_po_items} items → 109")
                else:
                    all_received = False
                    print(f"⚠️ Could not fetch PO items to check completion: {cat_resp.status_code}")
                
                new_status = 239 if all_received else 109
                status_label = "GOODS RECEIVED" if all_received else "NOT COMPLETELY SUPPLIED (partial)"
                print(f"=== SETTING {status_label} STATUS ({new_status}) for PO {po_id} ===")
                
                gr_response = simpro_request('PATCH', f'/companies/{COMPANY_ID}/vendorOrders/{po_id}', json={'Status': new_status})
                print(f"Status API Response: {gr_response.status_code}")
                if gr_response.status_code == 204:
                    goods_received_set = True
                    print(f"✅ {status_label} status set successfully for PO {po_id}")
                else:
                    print(f"⚠️ Status update returned: {gr_response.status_code} - {gr_response.text}")
            except Exception as gr_err:
                print(f"⚠️ Failed to set PO status: {gr_err}")
        
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
            'mergeCorrections': merge_corrections,
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

@app.route('/api/job-materials', methods=['POST'])
@login_required
def job_materials():
    """Get all materials for a job with their current storage locations from CC assignments"""
    try:
        data = request.get_json()
        job_id = str(data.get("jobId", "")).strip()
        if not job_id:
            return jsonify({"error": "jobId is required"}), 400

        print(f"[job-materials] Looking up job {job_id}")

        # 1. Get job info
        job_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/jobs/?ID={job_id}&columns=ID,Name,Customer")
        if job_resp.status_code != 200:
            return jsonify({"error": f"Job {job_id} not found"}), 404
        job_list = job_resp.json()
        if not isinstance(job_list, list) or len(job_list) == 0:
            return jsonify({"error": f"Job {job_id} not found"}), 404
        job_data = job_list[0]
        job_info = {
            "id": str(job_data.get("ID", job_id)),
            "number": job_data.get("Name", f"J{job_id}"),
            "customer": ""
        }
        cust = job_data.get("Customer")
        if cust:
            job_info["customer"] = cust.get("CompanyName", "") or cust.get("Name", "")

        # 2. Get sections
        sections_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/")
        if sections_resp.status_code != 200:
            return jsonify({"error": "Failed to get job sections"}), 500
        sections = sections_resp.json()
        if not isinstance(sections, list):
            sections = []

        # 3. For each section -> cost centres -> stock
        items = []
        for section in sections:
            sec_id = section.get("ID")
            if not sec_id:
                continue

            cc_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/")
            if cc_resp.status_code != 200:
                continue
            cost_centres = cc_resp.json()
            if not isinstance(cost_centres, list):
                continue

            for cc in cost_centres:
                cc_id = cc.get("ID")
                if not cc_id:
                    continue
                cc_name = cc.get("Name", "")

                stock_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/{cc_id}/stock/")
                if stock_resp.status_code != 200:
                    continue
                stock_items = stock_resp.json()
                if not isinstance(stock_items, list):
                    continue

                for stock_item in stock_items:
                    catalog = stock_item.get("Catalog", {})
                    cat_id = catalog.get("ID")
                    if not cat_id:
                        continue

                    qty_data = stock_item.get("Quantity", {})
                    if isinstance(qty_data, dict):
                        required_qty = qty_data.get("Required", 0) or 0
                        assigned_qty = qty_data.get("Assigned", 0) or 0
                    else:
                        required_qty = qty_data if qty_data else 0
                        assigned_qty = 0

                    # Get AssignedBreakdown for current location
                    assigned_breakdown = stock_item.get("AssignedBreakdown", [])
                    if not assigned_breakdown or not isinstance(assigned_breakdown, list):
                        continue

                    for ab in assigned_breakdown:
                        storage = ab.get("Storage", {})
                        ab_qty = ab.get("Quantity", 0)
                        if ab_qty <= 0:
                            continue

                        storage_id = storage.get("ID") if isinstance(storage, dict) else storage
                        storage_name = storage.get("Name", f"Storage {storage_id}") if isinstance(storage, dict) else f"Storage {storage_id}"

                        items.append({
                            "catalogId": cat_id,
                            "name": catalog.get("Name", ""),
                            "partNo": catalog.get("PartNo", "") or catalog.get("Sku", ""),
                            "qty": ab_qty,
                            "requiredQty": required_qty,
                            "assignedQty": assigned_qty,
                            "currentStorage": {"id": storage_id, "name": storage_name},
                            "sectionId": sec_id,
                            "costCentreId": cc_id,
                            "costCentreName": cc_name
                        })

        print(f"[job-materials] Found {len(items)} assigned materials for job {job_id}")
        return jsonify({"job": job_info, "items": items})

    except Exception as e:
        print(f"[job-materials] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/relocate', methods=['POST'])
@login_required
def relocate_items():
    """Relocate job-allocated items using 3-step CC process"""
    try:
        data = request.get_json()
        
        dest_id = data.get('destId')
        dest_name = data.get('destName', 'Unknown')
        items = data.get('items', [])
        job_id = data.get('jobId')
        job_number = data.get('jobNumber', '')
        customer = data.get('customer', '')
        staff_member = session.get('username', 'unknown')
        staff_name = session.get('display_name', staff_member)
        
        if not dest_id or not items:
            return jsonify({'error': 'Missing required fields'}), 400
        
        results = []
        success_count = 0
        fail_count = 0
        label_items = []
        
        for item in items:
            catalog_id = item.get('catalogId')
            quantity = int(item.get('qty', 1))
            source_id = item.get('fromStorageId')
            source_name = item.get('fromStorageName', 'Unknown')
            section_id = item.get('sectionId')
            cc_id = item.get('costCentreId')
            part_no = item.get('partNo', '')
            name = item.get('name', '')
            
            if not catalog_id or not source_id:
                results.append({'catalogId': catalog_id, 'success': False, 'error': 'Missing catalogId or source'})
                fail_count += 1
                continue
            
            # Skip if source == destination
            if int(source_id) == int(dest_id):
                results.append({'catalogId': catalog_id, 'success': True, 'note': 'Already in destination'})
                success_count += 1
                label_items.append({
                    'partNo': part_no, 'name': name, 'qty': quantity,
                    'storage': dest_name, 'jobNumber': job_number, 'customer': customer
                })
                continue
            
            item_success = True
            item_error = ''
            
            # Step 1: Un-assign from CC at source
            if section_id and cc_id:
                print(f"[relocate] Step 1: Un-assign cat {catalog_id} from storage {source_id} on job {job_id}")
                unassign_resp = simpro_request('PATCH',
                    f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/{catalog_id}/',
                    json={"AssignedBreakdown": [{"Storage": int(source_id), "Quantity": 0}]}
                )
                print(f"[relocate] Step 1 response: {unassign_resp.status_code}")
                if unassign_resp.status_code not in (200, 204):
                    item_success = False
                    item_error = f'Failed to un-assign from CC: {unassign_resp.status_code}'
                    print(f"[relocate] Step 1 FAILED: {unassign_resp.text}")
            
            # Step 2: Stock transfer
            if item_success:
                print(f"[relocate] Step 2: Transfer cat {catalog_id} from {source_id} to {dest_id}")
                transfer_resp = simpro_request('POST',
                    f'/companies/{COMPANY_ID}/stockTransfer/',
                    json={
                        "Catalog": int(catalog_id),
                        "FromStorage": int(source_id),
                        "ToStorage": int(dest_id),
                        "Quantity": int(quantity)
                    }
                )
                print(f"[relocate] Step 2 response: {transfer_resp.status_code}")
                if transfer_resp.status_code not in (200, 201, 204):
                    item_success = False
                    item_error = f'Stock transfer failed: {transfer_resp.status_code} - {transfer_resp.text}'
                    print(f"[relocate] Step 2 FAILED: {transfer_resp.text}")
                    # Rollback: re-assign at source
                    if section_id and cc_id:
                        simpro_request('POST',
                            f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/',
                            json={"Catalog": int(catalog_id), "AssignedBreakdown": [{"Storage": int(source_id), "Quantity": int(quantity)}]}
                        )
            
            # Step 3: Re-assign to CC at destination
            if item_success and section_id and cc_id:
                print(f"[relocate] Step 3: Re-assign cat {catalog_id} to storage {dest_id} on job {job_id}")
                reassign_resp = simpro_request('POST',
                    f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/',
                    json={"Catalog": int(catalog_id), "AssignedBreakdown": [{"Storage": int(dest_id), "Quantity": int(quantity)}]}
                )
                print(f"[relocate] Step 3 response: {reassign_resp.status_code}")
                if reassign_resp.status_code not in (200, 201):
                    item_success = False
                    item_error = f'CC re-assignment failed: {reassign_resp.status_code} - {reassign_resp.text}'
                    print(f"[relocate] Step 3 FAILED: {reassign_resp.text}")
            
            if item_success:
                success_count += 1
                label_items.append({
                    'partNo': part_no, 'name': name, 'qty': quantity,
                    'storage': dest_name, 'jobNumber': job_number, 'customer': customer
                })
            else:
                fail_count += 1
            
            results.append({
                'catalogId': catalog_id, 'partNo': part_no,
                'success': item_success, 'error': item_error if not item_success else None
            })
        
        # Log the transfer
        if success_count > 0:
            staff_id = session.get('staff_id')
            log_allocation(
                staff_id=staff_id, staff_name=staff_name,
                po_number='', job_number=job_number, vendor_name='',
                items_count=success_count, storage_location=dest_name,
                allocation_type='relocate', verified=1
            )
        
        return jsonify({
            'success': fail_count == 0, 'successCount': success_count,
            'failCount': fail_count, 'results': results,
            'labelItems': label_items, 'movedBy': staff_name
        })
        
    except Exception as e:
        print(f"[relocate] Error: {e}")
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
        if USE_POSTGRES:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename=%s", ('pending_relocations',))
        else:
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
# Job Intel Endpoint
# ============================================
@app.route('/api/job-intel', methods=['POST'])
@login_required
def job_intel():
    """Get job stock intel - what's already received, what's pending, where it is"""
    try:
        data = request.json
        job_id = data.get('job_id')

        if not job_id:
            return jsonify({"error": "job_id required"}), 400

        # 1. Get job details (no trailing slash for single resource)
        job_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}?columns=ID,Name,Customer,Site')
        if job_resp.status_code != 200:
            return jsonify({"error": f"Job {job_id} not found"}), 404
        job = job_resp.json()

        job_info = {
            "id": job_id,
            "name": job.get("Name", ""),
            "customer": job.get("Customer", {}).get("CompanyName", ""),
            "site": job.get("Site", {}).get("Name", "")
        }

        # 2. Get sections
        sec_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/')
        sections = sec_resp.json() if sec_resp.status_code == 200 else []

        # 3. For each section, get cost centers and stock
        all_stock = []
        cc_names = {}

        for section in sections:
            sec_id = section["ID"]
            cc_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/')
            ccs = cc_resp.json() if cc_resp.status_code == 200 else []

            for cc in ccs:
                cc_id = cc["ID"]
                cc_name = cc.get("Name", "")
                cc_names[cc_id] = cc_name

                stock_resp = simpro_request('GET', f'/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/{cc_id}/stock/')
                if stock_resp.status_code == 200:
                    stock_items = stock_resp.json()
                    for item in stock_items:
                        item["_cc_name"] = cc_name
                        item["_cc_id"] = cc_id
                        item["_section_id"] = sec_id
                        all_stock.append(item)

        # 4. Build response
        stock_list = []
        storage_map = {}

        for s in all_stock:
            req_qty = s.get("Quantity", {}).get("Required", 0)
            assigned_qty = s.get("Quantity", {}).get("Assigned", 0)

            if req_qty == 0 and assigned_qty == 0:
                continue

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


# ============================================
# Fault Report Endpoints
# ============================================
FAULT_WEBHOOK_URL = os.environ.get('FAULT_WEBHOOK_URL', '')

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


@app.route('/api/fault-reports/submit', methods=['POST'])
@login_required
def submit_fault_report():
    """Submit a fault report from the app and forward to webhook."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing request body'}), 400
        
        import uuid
        report_id = str(uuid.uuid4())[:8]
        reporter_name = data.get('reporter_name', 'Unknown')
        reporter_email = data.get('reporter_email', '')
        description = data.get('description', '')
        current_screen = data.get('current_screen', '')
        staff_user = data.get('staff_user', '')
        
        # Save to database
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO fault_reports (id, reporter_name, reporter_email, description, current_screen, staff_user, status)
            VALUES (?, ?, ?, ?, ?, ?, 'new')
        """, (report_id, reporter_name, reporter_email or 'unknown', description, current_screen, staff_user))
        db.commit()
        
        # Forward to webhook if configured
        webhook_url = os.environ.get('FAULT_WEBHOOK_URL', '')
        if webhook_url:
            try:
                import requests as req
                webhook_payload = {
                    'type': 'fault_report',
                    'report_id': report_id,
                    'reporter_name': reporter_name,
                    'reporter_email': reporter_email,
                    'description': description,
                    'current_screen': current_screen,
                    'staff_user': staff_user,
                    'timestamp': datetime.now().isoformat()
                }
                req.post(webhook_url, json=webhook_payload, timeout=5)
            except Exception as e:
                print(f"[{datetime.now()}] Webhook forward failed: {e}")
        
        return jsonify({'success': True, 'report_id': report_id})
        
    except Exception as e:
        print(f"[{datetime.now()}] Fault report error: {e}")
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
# Job Stock Search & Allocate from Stock (v2)
# ============================================

@app.route('/api/job-stock-search', methods=['POST'])
@login_required
def job_stock_search():
    """Search for job materials that are available in stock"""
    try:
        data = request.get_json()
        job_id = str(data.get("jobId", "")).strip()
        if not job_id:
            return jsonify({"error": "jobId is required"}), 400

        print(f"[job-stock-search] Searching job {job_id}")

        # 1. Get job info (use list endpoint with ID filter - direct lookup returns 404)
        job_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/jobs/?ID={job_id}&columns=ID,Name,Customer")
        if job_resp.status_code != 200:
            return jsonify({"error": f"Job {job_id} not found (HTTP {job_resp.status_code})"}), 404
        job_list = job_resp.json()
        if not isinstance(job_list, list) or len(job_list) == 0:
            return jsonify({"error": f"Job {job_id} not found"}), 404
        job_data = job_list[0]
        job_info = {
            "id": str(job_data.get("ID", job_id)),
            "number": job_data.get("Name", f"J{job_id}"),
            "customer": ""
        }
        cust = job_data.get("Customer")
        if cust:
            job_info["customer"] = cust.get("CompanyName", "") or cust.get("Name", "")

        # 2. Get sections
        sections_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/")
        if sections_resp.status_code != 200:
            return jsonify({"error": "Failed to get job sections"}), 500
        sections = sections_resp.json()
        if not isinstance(sections, list):
            sections = []

        # 3. For each section, get cost centres and their stock/materials
        job_materials = []
        for section in sections:
            sec_id = section.get("ID")
            if not sec_id:
                continue
            sec_name = section.get("Name", "")

            cc_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/")
            if cc_resp.status_code != 200:
                continue
            cost_centres = cc_resp.json()
            if not isinstance(cost_centres, list):
                continue

            for cc in cost_centres:
                cc_id = cc.get("ID")
                if not cc_id:
                    continue
                cc_name = cc.get("Name", "")

                stock_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{sec_id}/costCenters/{cc_id}/stock/")
                if stock_resp.status_code != 200:
                    continue
                stock_items = stock_resp.json()
                if not isinstance(stock_items, list):
                    continue

                for item in stock_items:
                    catalog = item.get("Catalog", {})
                    cat_id = catalog.get("ID")
                    if not cat_id:
                        continue

                    qty_data = item.get("Quantity", {})
                    if isinstance(qty_data, dict):
                        required_qty = qty_data.get("Required", 0) or 0
                        assigned_qty = qty_data.get("Assigned", 0) or 0
                    else:
                        required_qty = qty_data if qty_data else 0
                        assigned_qty = 0

                    needed = required_qty - assigned_qty
                    if needed <= 0:
                        continue

                    job_materials.append({
                        "catalogId": cat_id,
                        "name": catalog.get("Name", ""),
                        "partNo": catalog.get("PartNo", "") or catalog.get("Sku", ""),
                        "requiredQty": required_qty,
                        "assignedQty": assigned_qty,
                        "neededQty": needed,
                        "sectionId": sec_id,
                        "sectionName": sec_name,
                        "costCentreId": cc_id,
                        "costCentreName": cc_name,
                        "assignedBreakdown": item.get("AssignedBreakdown", [])
                    })

        # Resolve catalog names (CC stock doesn't include them)
        # For pre-build/one-off items, catalog endpoint returns 404 — try storage device stock as fallback
        for mat in job_materials:
            if not mat.get("name"):
                cat_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/catalogs/{mat['catalogId']}/")
                if cat_resp.status_code == 200:
                    cat_data = cat_resp.json()
                    mat["name"] = cat_data.get("Name", "") or cat_data.get("Description", "")
                    mat["partNo"] = cat_data.get("PartNo", "") or mat.get("partNo", "")
                elif cat_resp.status_code == 404:
                    # Pre-build/one-off item — try storage device stock for name
                    for bd in mat.get("assignedBreakdown", []):
                        s = bd.get("Storage", {})
                        s_id = s.get("ID") if isinstance(s, dict) else s
                        if s_id:
                            try:
                                sd_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/storageDevices/{s_id}/stock/?Catalog.ID={mat['catalogId']}&pageSize=5")
                                if sd_resp.status_code == 200:
                                    for sd_item in sd_resp.json():
                                        sd_cat = sd_item.get("Catalog", {})
                                        if isinstance(sd_cat, dict) and sd_cat.get("ID") == mat['catalogId']:
                                            mat["name"] = sd_cat.get("Name", "") or ""
                                            mat["partNo"] = sd_cat.get("PartNumber", "") or ""
                                            break
                                    if mat.get("name"):
                                        break
                            except Exception:
                                pass

        if not job_materials:
            return jsonify({"job": job_info, "items": [], "message": "No unassigned materials found on this job"})

        print(f"[job-stock-search] Found {len(job_materials)} needed materials, scanning storage devices...")

        # Build catalog IDs we need to find
        needed_catalog_ids = set(m["catalogId"] for m in job_materials)

        # 5. Check AssignedBreakdown InStock FIRST (instant — no API calls)
        # Then only scan inventories for items with no breakdown data
        matched_items = []
        need_scan_ids = []
        for mat in job_materials:
            cat_id = mat["catalogId"]
            breakdown = mat.get("assignedBreakdown", [])
            bd_locations = []
            for bd in breakdown:
                in_stock = bd.get("InStock", 0)
                if in_stock and in_stock > 0:
                    storage = bd.get("Storage", {})
                    s_id = storage.get("ID") if isinstance(storage, dict) else storage
                    s_name = storage.get("Name", f"Storage {s_id}") if isinstance(storage, dict) else f"Storage {s_id}"
                    bd_locations.append({"storageId": s_id, "storageName": s_name, "availableQty": in_stock})
            if bd_locations:
                bd_locations.sort(key=lambda x: x["availableQty"], reverse=True)
                mat["stockLocations"] = bd_locations
                matched_items.append(mat)
                print(f"[job-stock-search] InStock hit: catalog {cat_id} — {len(bd_locations)} locations via AssignedBreakdown")
            else:
                need_scan_ids.append(cat_id)

        # 6. For items without InStock data, bulk-scan ALL storage devices (one pass, not per-item)
        if need_scan_ids:
            print(f"[job-stock-search] Bulk-scanning ALL storage devices for {len(need_scan_ids)} items...")
            # Get full device list
            dev_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/storageDevices/?pageSize=250")
            all_devices = []
            if dev_resp.status_code == 200:
                all_devices = [(d["ID"], d.get("Name", f"Device {d['ID']}")) for d in dev_resp.json()]
            print(f"[job-stock-search] Scanning {len(all_devices)} storage devices...")

            quick_map = {}
            need_scan_set = set(need_scan_ids)

            def _scan_device(dev_tuple):
                dev_id, dev_name = dev_tuple
                found = []
                try:
                    page = 1
                    while True:
                        sd_resp = simpro_request("GET", f"/companies/{COMPANY_ID}/storageDevices/{dev_id}/stock/?pageSize=250&page={page}")
                        if sd_resp.status_code != 200:
                            break
                        items = sd_resp.json()
                        if not items:
                            break
                        for st_item in items:
                            sc = st_item.get("Catalog", {})
                            sc_id = sc.get("ID")
                            if sc_id in need_scan_set:
                                ic = st_item.get("InventoryCount", 0)
                                if ic and ic > 0:
                                    found.append((sc_id, dev_id, dev_name, ic))
                        if len(items) < 250:
                            break
                        page += 1
                except Exception:
                    pass
                return found

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(_scan_device, all_devices)
                for device_results in results:
                    for cat_id, dev_id, dev_name, qty in device_results:
                        if cat_id not in quick_map:
                            quick_map[cat_id] = []
                        quick_map[cat_id].append({"storageId": dev_id, "storageName": dev_name, "availableQty": qty})

            for mat in job_materials:
                cat_id = mat["catalogId"]
                if cat_id in quick_map and not mat.get("stockLocations"):
                    locations = quick_map[cat_id]
                    locations.sort(key=lambda x: x["availableQty"], reverse=True)
                    mat["stockLocations"] = locations
                    matched_items.append(mat)
            print(f"[job-stock-search] Bulk scan found {len(quick_map)} items with stock across {len(all_devices)} devices")

        print(f"[job-stock-search] {len(matched_items)} items have stock available")

        return jsonify({
            "job": job_info,
            "items": matched_items
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/allocate-from-stock', methods=['POST'])
@login_required
def allocate_from_stock_v2():
    """Transfer stock and assign to job cost centre"""
    try:
        data = request.get_json()
        job_id = str(data.get("jobId", "")).strip()
        dest_storage_id = data.get("destinationStorageId")
        dest_storage_name = data.get("destinationStorageName", "")
        items = data.get("items", [])

        if not job_id:
            return jsonify({"error": "jobId is required"}), 400
        if not dest_storage_id:
            return jsonify({"error": "destinationStorageId is required"}), 400
        if not items:
            return jsonify({"error": "No items provided"}), 400

        print(f"[allocate-from-stock] Job {job_id}, destination {dest_storage_name} (ID {dest_storage_id}), {len(items)} items")

        results = []
        for item in items:
            cat_id = item.get("catalogId")
            src_id = item.get("sourceStorageId")
            src_name = item.get("sourceStorageName", "")
            quantity = item.get("quantity", 1)
            section_id = item.get("sectionId")
            cc_id = item.get("costCentreId")
            item_name = item.get("name", "")
            part_no = item.get("partNo", "")

            result_entry = {"catalogId": cat_id, "name": item_name, "partNo": part_no, "success": False}

            try:
                # Step 1: Stock transfer (if source != destination)
                if str(src_id) != str(dest_storage_id):
                    print(f"  Transferring {quantity}x {part_no} from {src_name} ({src_id}) to {dest_storage_name} ({dest_storage_id})")
                    # Try flat format first (works for regular catalog items)
                    transfer_payload = {
                        "Catalog": int(cat_id),
                        "FromStorage": int(src_id),
                        "ToStorage": int(dest_storage_id),
                        "Quantity": int(quantity)
                    }
                    transfer_resp = simpro_request("POST", f"/companies/{COMPANY_ID}/stockTransfer/", json=transfer_payload)
                    if transfer_resp.status_code not in (200, 201, 204):
                        # Fallback: SourceStorageDeviceID + Items format (works for pre-build/one-off items)
                        print(f"  Flat format failed ({transfer_resp.status_code}), trying SourceStorageDeviceID format...")
                        alt_payload = {
                            "SourceStorageDeviceID": int(src_id),
                            "Items": [{"CatalogID": int(cat_id), "Quantity": int(quantity), "DestinationStorageDeviceID": int(dest_storage_id)}]
                        }
                        transfer_resp = simpro_request("POST", f"/companies/{COMPANY_ID}/stockTransfer/", json=alt_payload)
                    if transfer_resp.status_code not in (200, 201, 204):
                        error_text = transfer_resp.text[:300]
                        print(f"  Transfer FAILED: {transfer_resp.status_code} {error_text}")
                        result_entry["success"] = False
                        result_entry["error"] = f"Stock transfer failed: HTTP {transfer_resp.status_code} - {error_text}"
                        result_entry["method"] = "transfer_failed"
                        results.append(result_entry)
                        continue
                    result_entry["method"] = "stock_transfer"
                else:
                    result_entry["method"] = "same_storage"
                    print(f"  Source == destination for {part_no}, skipping transfer")

                # Step 2: Assign to job cost centre (MANDATORY — must succeed)
                assign_ok = False
                if section_id and cc_id:
                    assign_payload = {
                        "Catalog": int(cat_id),
                        "AssignedBreakdown": [{
                            "Storage": int(dest_storage_id),
                            "Quantity": int(quantity)
                        }]
                    }
                    assign_url = f"/companies/{COMPANY_ID}/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/"
                    print(f"  Assigning {quantity}x {part_no} to CC {cc_id} at storage {dest_storage_id}")
                    assign_resp = simpro_request("POST", assign_url, json=assign_payload)

                    if assign_resp.status_code in (200, 201, 204):
                        print(f"  ✅ CC assign succeeded")
                        assign_ok = True
                    else:
                        print(f"  ❌ CC assign FAILED: {assign_resp.status_code} — {assign_resp.text[:300]}")
                        assign_ok = False
                else:
                    print(f"  ⚠️ Missing sectionId ({section_id}) or costCentreId ({cc_id}) — cannot assign to CC")
                    assign_ok = False

                if assign_ok:
                    result_entry["success"] = True
                    result_entry["message"] = f"Moved {quantity} from {src_name} to {dest_storage_name} and assigned to job"
                else:
                    # Stock may have transferred but CC assignment failed — report as failure
                    result_entry["success"] = False
                    result_entry["error"] = f"Stock transferred but CC assignment failed — item not assigned to job. sectionId={section_id}, ccId={cc_id}"
                    result_entry["message"] = f"Moved stock but FAILED to assign to job"

                # Update stock cache in-place (deduct from source)
                _deduct_from_cache(int(cat_id), int(src_id), int(quantity))

                # Log to allocation_log if table exists
                try:
                    db = get_db()
                    db.execute(
                        "INSERT INTO allocation_log (timestamp, job_id, catalog_id, part_no, description, quantity, source_storage, dest_storage, staff_id, method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (datetime.now().isoformat(), job_id, cat_id, part_no, item_name, quantity, src_name, dest_storage_name, session.get("staff_id", ""), "stock_allocation_v2")
                    )
                    db.commit()
                except Exception:
                    pass  # Table may not exist

            except Exception as e:
                print(f"  Error processing {part_no}: {e}")
                result_entry["success"] = False
                result_entry["error"] = str(e)

            results.append(result_entry)

        success_count = sum(1 for r in results if r.get("success"))
        print(f"[allocate-from-stock] Done: {success_count}/{len(results)} succeeded")

        return jsonify({
            "results": results,
            "successCount": success_count,
            "totalCount": len(results)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================
# Initialize and Run
# ============================================
# Initialize database on module load (for gunicorn)
print("Initializing database...")
init_db()

if USE_POSTGRES:
    print("\u2705 Using PostgreSQL database (persistent)")
else:
    print("\u26a0\ufe0f Using SQLite database (ephemeral)")



# ============================================================
# COLLECTION API ENDPOINTS
# ============================================================

@app.route('/api/collection/job-lookup', methods=['GET'])
@login_required
def collection_job_lookup():
    """Look up job for collection - search by job number, customer name, or phone"""
    query = request.args.get('q', request.args.get('job', '')).strip()
    if not query:
        return jsonify({'error': 'Search term required'}), 400

    try:
        token = get_simpro_token()
        if not token:
            return jsonify({'error': 'Could not get Simpro token'}), 500

        base_url = 'https://2ndfix.simprosuite.com/api/v1.0'
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

        job_data = None
        is_job_number = query.isdigit()
        is_phone = bool(re.match(r'^[\d\s\+\-\(\)]{6,}$', query))

        if is_job_number:
            # Direct job number lookup
            resp = requests.get(f'{base_url}/companies/3/jobs/?ID={query}&columns=ID,Name,Customer,Site', headers=headers)
            if resp.status_code == 200:
                job_list = resp.json()
                if isinstance(job_list, list) and len(job_list) > 0:
                    job_data = job_list[0]
        else:
            # Search by customer name or phone
            customers = []
            if is_phone:
                phone_clean = re.sub(r'[\s\-\(\)]', '', query)
                cr = requests.get(f'{base_url}/companies/3/customers/?Phone={phone_clean}&columns=ID,CompanyName,GivenName,FamilyName,Phone&pageSize=20', headers=headers)
                if cr.status_code == 200 and isinstance(cr.json(), list):
                    customers.extend(cr.json())
            else:
                # Search name across CompanyName, FamilyName, GivenName
                cr = requests.get(f'{base_url}/companies/3/customers/?search=any&CompanyName={query}&FamilyName={query}&GivenName={query}&columns=ID,CompanyName,GivenName,FamilyName,Phone&pageSize=20', headers=headers)
                if cr.status_code == 200 and isinstance(cr.json(), list):
                    customers.extend(cr.json())

            if not customers:
                return jsonify({'error': f'No customers found for "{query}"'}), 404

            # Find jobs for matching customers
            matching_jobs = []
            for cust in customers[:10]:
                cust_id = cust.get('ID')
                cust_name = cust.get('CompanyName') or ((cust.get('GivenName', '') + ' ' + cust.get('FamilyName', '')).strip())
                cust_phone = cust.get('Phone', '')
                jr = requests.get(f'{base_url}/companies/3/jobs/?Customer={cust_id}&columns=ID,Name,Customer,Site&pageSize=20', headers=headers)
                if jr.status_code == 200 and isinstance(jr.json(), list):
                    for j in jr.json():
                        matching_jobs.append({
                            'id': j['ID'], 'name': j.get('Name', ''),
                            'customer_name': cust_name, 'customer_phone': cust_phone
                        })

            if not matching_jobs:
                return jsonify({'error': f'No jobs found for "{query}"'}), 404

            if len(matching_jobs) == 1:
                # Single match - load directly
                resp = requests.get(f'{base_url}/companies/3/jobs/?ID={matching_jobs[0]["id"]}&columns=ID,Name,Customer,Site', headers=headers)
                if resp.status_code == 200:
                    jl = resp.json()
                    if isinstance(jl, list) and len(jl) > 0:
                        job_data = jl[0]
            else:
                return jsonify({'multiple': True, 'jobs': matching_jobs})

        if not job_data:
            return jsonify({'error': f'Job not found for "{query}"'}), 404

        job_id = job_data.get('ID', job_data.get('id'))
        job_name = job_data.get('Name', '')
        job_input = str(job_id)  # backwards compat

        # Get customer details
        customer_ref = job_data.get('Customer', {})
        customer_id = customer_ref.get('ID')
        customer = {'name': customer_ref.get('CompanyName', ''), 'email': '', 'phone': '', 'mobile': '', 'address': ''}

        if customer_id:
            try:
                cresp = requests.get(f'{base_url}/companies/3/customers/{customer_id}/', headers=headers)
                if cresp.status_code == 200:
                    cd = cresp.json()
                    cname = cd.get('CompanyName', '')
                    if not cname:
                        cname = (cd.get('GivenName', '') + ' ' + cd.get('FamilyName', '')).strip()
                    customer['name'] = cname or customer_ref.get('CompanyName', '')
                    customer['email'] = cd.get('Email', '')
                    customer['phone'] = cd.get('Phone', cd.get('WorkPhone', ''))
                    customer['mobile'] = cd.get('CellPhone', cd.get('Mobile', ''))
                    if not customer['phone'] and customer['mobile']:
                        customer['phone'] = customer['mobile']
                    addr = cd.get('Address', {})
                    if isinstance(addr, dict):
                        parts = [addr.get('Address', ''), addr.get('City', ''), addr.get('State', ''), addr.get('PostCode', '')]
                        customer['address'] = ', '.join(p for p in parts if p)
                    elif isinstance(addr, str):
                        customer['address'] = addr
            except Exception as e:
                print(f"Warning: Could not fetch customer details: {e}")

        # Site address fallback
        if not customer['address']:
            site = job_data.get('Site', {})
            if site and site.get('Name'):
                customer['address'] = site.get('Name', '')

        # Get job materials from CC data
        materials = []
        try:
            sresp = requests.get(f'{base_url}/companies/3/jobs/{job_id}/sections/', headers=headers)
            if sresp.status_code == 200:
                for section in sresp.json():
                    section_id = section.get('ID')
                    ccresp = requests.get(f'{base_url}/companies/3/jobs/{job_id}/sections/{section_id}/costCenters/', headers=headers)
                    if ccresp.status_code == 200:
                        for cc in ccresp.json():
                            cc_id = cc.get('ID')
                            cc_name = cc.get('Name', '')
                            stkresp = requests.get(f'{base_url}/companies/3/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/', headers=headers)
                            if stkresp.status_code == 200:
                                for item in stkresp.json():
                                    cat = item.get('Catalog', {})
                                    qty_obj = item.get('Quantity', {})
                                    if isinstance(qty_obj, dict):
                                        assigned = qty_obj.get('Assigned', 0)
                                        required = qty_obj.get('Required', 0)
                                    else:
                                        assigned = qty_obj or 0
                                        required = assigned
                                    if assigned <= 0 and required <= 0:
                                        continue
                                    storage_name = 'Unknown'
                                    storage_id = None
                                    for bd in item.get('AssignedBreakdown', []):
                                        if bd.get('Quantity', 0) > 0:
                                            st = bd.get('Storage', {})
                                            storage_name = st.get('Name', 'Unknown')
                                            storage_id = st.get('ID')
                                            break
                                    materials.append({
                                        'catalogId': cat.get('ID'),
                                        'partCode': cat.get('PartNo', ''),
                                        'description': cat.get('Name', ''),
                                        'quantity': required,
                                        'assigned': assigned,
                                        'storage': storage_name,
                                        'storageId': storage_id,
                                        'sectionId': section_id,
                                        'costCentreId': cc_id,
                                        'costCentreName': cc_name
                                    })
        except Exception as e:
            print(f"Warning: Could not fetch materials: {e}")

        # Get collection history from DB
        history = []
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute(
                'SELECT id, collected_by, staff_name, created_at, notes, vehicle_rego, status '
                'FROM collections WHERE job_number = %s ORDER BY created_at DESC',
                (str(job_input),)
            )
            for col in cursor.fetchall():
                col_id = col['id']
                cursor.execute(
                    'SELECT part_code, description, quantity, storage_location '
                    'FROM collection_items WHERE collection_id = %s', (col_id,)
                )
                items_rows = [dict(r) for r in cursor.fetchall()]
                history.append({
                    'id': col_id,
                    'collectedBy': col['collected_by'],
                    'staffName': col['staff_name'],
                    'date': col['created_at'].isoformat() if col['created_at'] else '',
                    'notes': col['notes'],
                    'vehicleRego': col['vehicle_rego'],
                    'status': col['status'],
                    'items': items_rows
                })
        except Exception as e:
            print(f"Warning: Could not fetch collection history: {e}")

        # Calculate collected quantities
        collected_qty = {}
        for h in history:
            if h.get('status') == 'completed':
                for it in h.get('items', []):
                    key = it.get('part_code', '')
                    collected_qty[key] = collected_qty.get(key, 0) + (it.get('quantity', 0))
        for m in materials:
            m['collected'] = collected_qty.get(m['partCode'], 0)
            m['remaining'] = max(0, m['assigned'] - m['collected'])

        return jsonify({
            'job': {'id': job_id, 'number': job_input, 'name': job_name},
            'customer': customer,
            'materials': materials,
            'history': history
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def generate_collection_pdf(collection_data):
    """Generate a Collection Receipt PDF using ReportLab. Returns PDF bytes."""
    import io
    import base64
    from datetime import datetime
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm,
                            leftMargin=15*mm, rightMargin=15*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('ReceiptTitle', parent=styles['Title'], fontSize=18,
                                  spaceAfter=6, textColor=colors.HexColor('#1a237e'))
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=11,
                                     textColor=colors.grey, spaceAfter=12)
    normal = styles['Normal']
    bold_style = ParagraphStyle('BoldNormal', parent=normal, fontName='Helvetica-Bold')

    elements = []

    # Header
    elements.append(Paragraph("2nd Fix Doors & Hardware", title_style))
    elements.append(Paragraph("Collection Receipt", subtitle_style))
    elements.append(Spacer(1, 4*mm))

    # Job info
    job_number = collection_data.get('job_number', '')
    customer_name = collection_data.get('customer_name', '')
    site_address = collection_data.get('site_address', '')
    collected_by = collection_data.get('collected_by', '')
    staff_name = collection_data.get('staff_name', '')
    collection_id = collection_data.get('collection_id', '')
    now_str = datetime.now().strftime('%d/%m/%Y at %I:%M %p')

    info_data = [
        ['Job Number:', str(job_number), 'Date/Time:', now_str],
        ['Customer:', str(customer_name), 'Collected By:', str(collected_by)],
        ['Site Address:', str(site_address), 'Processed By:', str(staff_name)],
    ]
    info_table = Table(info_data, colWidths=[80, 170, 80, 170])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 8*mm))

    # Items table
    elements.append(Paragraph("Items Collected", bold_style))
    elements.append(Spacer(1, 3*mm))

    items = collection_data.get('items', [])
    table_data = [['Part Code', 'Description', 'Qty', 'Storage Location']]
    for it in items:
        table_data.append([
            str(it.get('partCode', it.get('part_code', ''))),
            str(it.get('description', '')),
            str(it.get('quantity', 0)),
            str(it.get('storage', it.get('storage_location', '')))
        ])

    items_table = Table(table_data, colWidths=[90, 230, 40, 140])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 10*mm))

    # Declaration
    elements.append(Paragraph(
        "<b>Declaration:</b> I confirm I have received the above items in good condition.",
        normal
    ))
    elements.append(Spacer(1, 8*mm))

    # Signature
    sig_data = collection_data.get('signature_data', '')
    if sig_data:
        try:
            sig_b64 = sig_data.split(',')[1] if ',' in sig_data else sig_data
            sig_bytes = base64.b64decode(sig_b64)
            sig_buf = io.BytesIO(sig_bytes)
            sig_img = RLImage(sig_buf, width=180, height=60)
            elements.append(Paragraph("Signature:", bold_style))
            elements.append(Spacer(1, 2*mm))
            elements.append(sig_img)
        except Exception as e:
            print(f"Warning: Could not embed signature in PDF: {e}")

    elements.append(Spacer(1, 6*mm))

    # Footer
    elements.append(Paragraph(
        f"<font size=8 color='grey'>Collection ID: {collection_id} | Generated: {now_str} | "
        f"251 Churchill Road, Prospect SA 5082 | 1300 263 349</font>",
        normal
    ))

    doc.build(elements)
    return buf.getvalue()


@app.route('/api/collection/complete', methods=['POST'])
@login_required
def collection_complete():
    """Save a completed collection with signature, photos, and send confirmation"""
    data = request.json or {}

    job_number = data.get('jobNumber')
    job_id = data.get('jobId')
    job_name = data.get('jobName', '')
    collected_by = data.get('collectedBy', '').strip()
    items = data.get('items', [])
    signature_data = data.get('signatureData', '')

    if not job_number or not collected_by or not items or not signature_data:
        return jsonify({'error': 'Missing required fields (job, name, items, signature)'}), 400

    staff_id = session.get('staff_id', 0)
    staff_name = session.get('staff_name', 'Unknown')

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            'INSERT INTO collections (job_number, job_id, job_name, customer_name, customer_email, '
            'customer_phone, site_address, collected_by, staff_id, staff_name, signature_data, '
            'notes, vehicle_rego, status) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (job_number, job_id, job_name,
             data.get('customerName',''), data.get('customerEmail',''),
             data.get('customerPhone',''), data.get('siteAddress',''),
             collected_by, staff_id, staff_name, signature_data,
             data.get('notes',''), data.get('vehicleRego',''), 'completed')
        )
        collection_id = cursor.fetchone()['id']

        for it in items:
            cursor.execute(
                'INSERT INTO collection_items (collection_id, catalog_id, part_code, '
                'description, quantity, storage_location, storage_id) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (collection_id, it.get('catalogId'), it.get('partCode',''),
                 it.get('description',''), it.get('quantity',0),
                 it.get('storage',''), it.get('storageId'))
            )

        for photo in data.get('photos', []):
            if photo:
                cursor.execute(
                    'INSERT INTO collection_photos (collection_id, photo_data) VALUES (%s,%s)',
                    (collection_id, photo)
                )

        db.commit()

        # Log allocation in main request before returning
        log_allocation(staff_id, staff_name, '', job_number, '', len(items), 'Customer Collection', 'collection', 1)

        # Gather data for background work (Simpro uploads, PDF, email, status)
        bg_data = {
            'job_id': job_id,
            'job_number': job_number,
            'job_name': job_name,
            'collected_by': collected_by,
            'staff_name': staff_name,
            'collection_id': collection_id,
            'signature_data': signature_data,
            'photos': data.get('photos', []),
            'items': items,
            'customer_name': data.get('customerName', ''),
            'customer_email': data.get('customerEmail', '').strip(),
            'customer_phone': data.get('customerPhone', ''),
            'site_address': data.get('siteAddress', ''),
        }
        threading.Thread(target=_collection_background_work, args=(bg_data,), daemon=True).start()

        return jsonify({'success': True, 'collectionId': collection_id})

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _collection_background_work(data):
    """Background thread: Simpro uploads, PDF generation, job status, confirmation email."""
    with app.app_context():
        try:
            job_id = data['job_id']
            job_number = data['job_number']
            collection_id = data['collection_id']
            signature_data = data['signature_data']
            collected_by = data['collected_by']
            staff_name = data['staff_name']
            items = data['items']

            # Upload signature to Simpro job as attachment
            if job_id and signature_data:
                try:
                    b64 = signature_data.split(',')[1] if ',' in signature_data else signature_data
                    from datetime import datetime
                    ts = datetime.now().strftime('%Y%m%d_%H%M')
                    simpro_request('POST', f'/companies/3/jobs/{job_id}/attachments/files/', json={
                        'Filename': f'Collection_Signature_{job_number}_{ts}.png',
                        'Base64Data': b64,
                        'Public': True
                    })
                    print(f"[BG] Uploaded signature to Simpro job {job_id}")
                except Exception as e:
                    print(f"[BG] Warning: Simpro signature upload failed: {e}")

            # Upload photos to Simpro job
            if job_id:
                photos_list = data.get('photos', [])
                from datetime import datetime as _dt
                date_str = _dt.now().strftime('%Y%m%d_%H%M')
                for idx, photo in enumerate(photos_list, 1):
                    if photo:
                        try:
                            photo_b64 = photo.split(',')[1] if ',' in photo else photo
                            simpro_request('POST', f'/companies/3/jobs/{job_id}/attachments/files/', json={
                                'Filename': f'Collection_{collection_id}_Photo_{idx}_{date_str}.jpg',
                                'Base64Data': photo_b64,
                                'Public': True
                            })
                            print(f"[BG] Uploaded photo {idx} to Simpro job {job_id}")
                        except Exception as e:
                            print(f"[BG] Warning: Simpro photo upload {idx} failed: {e}")

            # Generate and upload Collection Receipt PDF to Simpro job
            if job_id:
                try:
                    import base64 as _b64
                    from datetime import datetime as _dt2
                    pdf_bytes = generate_collection_pdf({
                        'job_number': job_number,
                        'customer_name': data.get('customer_name', ''),
                        'site_address': data.get('site_address', ''),
                        'collected_by': collected_by,
                        'staff_name': staff_name,
                        'collection_id': collection_id,
                        'items': items,
                        'signature_data': signature_data
                    })
                    pdf_b64 = _b64.b64encode(pdf_bytes).decode('utf-8')
                    pdf_date = _dt2.now().strftime('%Y%m%d_%H%M')
                    simpro_request('POST', f'/companies/3/jobs/{job_id}/attachments/files/', json={
                        'Filename': f'Collection_Receipt_{job_number}_{pdf_date}.pdf',
                        'Base64Data': pdf_b64,
                        'Public': True
                    })
                    print(f"[BG] Uploaded Collection Receipt PDF to Simpro job {job_id}")
                except Exception as e:
                    print(f"[BG] Warning: PDF generation/upload failed: {e}")
                    import traceback; traceback.print_exc()

            # Set job status based on partial/full collection
            if job_id:
                try:
                    # Get total required materials for job from Simpro
                    token = get_simpro_token()
                    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                    base_url = 'https://2ndfix.simprosuite.com/api/v1.0'
                    required_by_catalog = {}
                    sresp = requests.get(f'{base_url}/companies/3/jobs/{job_id}/sections/', headers=headers, timeout=15)
                    if sresp.status_code == 200:
                        for section in sresp.json():
                            section_id = section.get('ID')
                            ccresp = requests.get(f'{base_url}/companies/3/jobs/{job_id}/sections/{section_id}/costCenters/', headers=headers, timeout=15)
                            if ccresp.status_code == 200:
                                for cc in ccresp.json():
                                    cc_id = cc.get('ID')
                                    stkresp = requests.get(f'{base_url}/companies/3/jobs/{job_id}/sections/{section_id}/costCenters/{cc_id}/stock/', headers=headers, timeout=15)
                                    if stkresp.status_code == 200:
                                        for item in stkresp.json():
                                            cat = item.get('Catalog', {})
                                            c_id = cat.get('ID')
                                            if not c_id:
                                                continue
                                            qty_obj = item.get('Quantity', {})
                                            if isinstance(qty_obj, dict):
                                                assigned = qty_obj.get('Assigned', 0) or 0
                                            else:
                                                assigned = qty_obj or 0
                                            if assigned > 0:
                                                required_by_catalog[c_id] = required_by_catalog.get(c_id, 0) + assigned

                    # Get total collected across ALL collections for this job
                    db2 = get_db()
                    cur2 = db2.cursor()
                    cur2.execute(
                        'SELECT ci.catalog_id, SUM(ci.quantity) as total_qty '
                        'FROM collection_items ci '
                        'JOIN collections c ON ci.collection_id = c.id '
                        'WHERE c.job_id = %s AND c.status = %s '
                        'GROUP BY ci.catalog_id',
                        (str(job_id), 'completed')
                    )
                    collected_by_catalog = {}
                    for row in cur2.fetchall():
                        cat_id = row['catalog_id']
                        if cat_id:
                            collected_by_catalog[int(cat_id)] = row['total_qty'] or 0

                    # Compare: fully collected if ALL required items have been collected
                    fully_collected = True
                    if not required_by_catalog:
                        fully_collected = False  # No materials found - don't assume full
                    else:
                        for cat_id, req_qty in required_by_catalog.items():
                            col_qty = collected_by_catalog.get(cat_id, 0)
                            if col_qty < req_qty:
                                fully_collected = False
                                break

                    status_id = 1331 if fully_collected else 1330
                    status_label = 'Fully Collected' if fully_collected else 'Partially Collected'
                    patch_resp = simpro_request('PATCH', f'/companies/3/jobs/{job_id}/', json={
                        'Status': {'ID': status_id}
                    })
                    print(f"[BG] Set job {job_id} status to {status_label} ({status_id}): HTTP {patch_resp.status_code}")
                except Exception as e:
                    print(f"[BG] Warning: Failed to set job status: {e}")
                    import traceback; traceback.print_exc()

            # Send confirmation email via Graph API
            customer_email = data.get('customer_email', '').strip()
            if customer_email:
                try:
                    _send_collection_confirmation(
                        customer_name=data.get('customer_name', ''),
                        customer_email=customer_email,
                        job_number=job_number,
                        job_name=data.get('job_name', ''),
                        items=items,
                        collected_by=collected_by,
                        collection_id=collection_id
                    )
                except Exception as e:
                    print(f"[BG] Warning: Confirmation email failed: {e}")

            print(f"[BG] Collection {collection_id} background work completed successfully")

        except Exception as e:
            print(f"[BG] Collection background work FAILED: {e}")
            import traceback; traceback.print_exc()


def _send_collection_confirmation(customer_name, customer_email, job_number, job_name, items, collected_by, collection_id):
    """Send collection confirmation email via Microsoft Graph API from orders@2ndfix.com.au"""
    import os as _os
    from datetime import datetime

    client_id = _os.environ.get('GRAPH_CLIENT_ID', '')
    client_secret = _os.environ.get('GRAPH_CLIENT_SECRET', '')
    tenant_id = _os.environ.get('GRAPH_TENANT_ID', '')

    if not client_id or not client_secret or not tenant_id:
        print("Graph API credentials not configured - skipping email")
        return

    token_resp = requests.post(
        f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token',
        data={
            'client_id': client_id, 'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials'
        }
    )
    if token_resp.status_code != 200:
        print(f"Graph token error: {token_resp.text}")
        return
    access_token = token_resp.json().get('access_token')

    now = datetime.now().strftime('%d/%m/%Y at %I:%M %p')
    items_html = ''.join(f'<li>{it.get("description","")} &mdash; Qty: {it.get("quantity",0)}</li>' for it in items)

    html_body = f"""
    <p>Hi {customer_name or 'there'},</p>
    <p>This confirms collection of the following items from <strong>2nd Fix Doors &amp; Hardware</strong>:</p>
    <ul>{items_html}</ul>
    <p><strong>Collected on:</strong> {now}<br>
    <strong>Job Number:</strong> {job_number}<br>
    <strong>Collected by:</strong> {collected_by}</p>
    <hr>
    <p>If there are any issues with your order, please contact us immediately on <strong>1300 263 349</strong>.</p>
    <p>Thank you,<br><strong>2nd Fix Doors &amp; Hardware</strong><br>
    251 Churchill Road, Prospect SA 5082<br>1300 263 349</p>
    """

    send_resp = requests.post(
        'https://graph.microsoft.com/v1.0/users/orders@2ndfix.com.au/sendMail',
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
        json={
            'message': {
                'subject': f'Collection Confirmation - Job {job_number}',
                'body': {'contentType': 'HTML', 'content': html_body},
                'toRecipients': [{'emailAddress': {'address': customer_email, 'name': customer_name or ''}}]
            }
        }
    )
    if send_resp.status_code in (200, 202):
        print(f"Collection confirmation email sent to {customer_email}")
    else:
        print(f"Email send failed: {send_resp.status_code} {send_resp.text}")


@app.route('/api/collection/history', methods=['GET'])
@login_required
def collection_history_api():
    """Get collection history, optionally filtered by job"""
    job = request.args.get('job', '').strip()
    db = get_db()
    cursor = db.cursor()
    if job:
        cursor.execute('SELECT * FROM collections WHERE job_number = %s ORDER BY created_at DESC', (job,))
    else:
        cursor.execute('SELECT * FROM collections ORDER BY created_at DESC LIMIT 50')
    rows = cursor.fetchall()
    result = []
    for r in rows:
        result.append({
            'id': r['id'], 'jobNumber': r['job_number'], 'jobName': r.get('job_name',''),
            'customerName': r['customer_name'], 'collectedBy': r['collected_by'],
            'staffName': r['staff_name'], 'date': r['created_at'].isoformat() if r['created_at'] else '',
            'notes': r['notes'], 'status': r['status']
        })
    return jsonify(result)



if __name__ == '__main__':
    print("Starting PO Receiving App server...")
    print("Staff management enabled")
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)


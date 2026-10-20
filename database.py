# database.py - SQLite storage
import sqlite3
from config import DB_FILE

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            amount REAL NOT NULL,
            customer_name TEXT,
            customer_email TEXT,
            status TEXT DEFAULT 'PENDING',
            utr TEXT UNIQUE,
            webhook_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified_at TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS verified_utrs (
            utr TEXT PRIMARY KEY,
            order_id TEXT,
            amount REAL,
            verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def create_order(order_id, amount, customer_name, customer_email, webhook_url):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO orders (order_id, amount, customer_name, customer_email, webhook_url, status)
        VALUES (?, ?, ?, ?, ?, 'PENDING')
    ''', (order_id, amount, customer_name, customer_email, webhook_url))
    conn.commit()
    conn.close()

def get_order(order_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM orders WHERE order_id = ?', (order_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def mark_order_success(order_id, utr):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        UPDATE orders 
        SET status = 'SUCCESS', utr = ?, verified_at = CURRENT_TIMESTAMP
        WHERE order_id = ?
    ''', (utr, order_id))
    cur.execute('''
        INSERT OR IGNORE INTO verified_utrs (utr, order_id, amount)
        VALUES (?, ?, (SELECT amount FROM orders WHERE order_id = ?))
    ''', (utr, order_id, order_id))
    conn.commit()
    conn.close()

def is_utr_duplicate(utr):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT utr FROM verified_utrs WHERE utr = ?', (str(utr).strip(),))
    res = cur.fetchone()
    conn.close()
    return res is not None

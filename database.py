import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.environ.get("DATA_DIR", "./data"), "akciofigyelo.db"))

def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            parent_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS chain_stores (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            image_url TEXT
        );

        CREATE TABLE IF NOT EXISTS shops (
            uuid TEXT PRIMARY KEY,
            chain_id TEXT,
            chain_name TEXT,
            postal_code TEXT,
            city TEXT,
            address TEXT,
            latitude REAL,
            longitude REAL,
            opening_time TEXT
        );

        CREATE TABLE IF NOT EXISTS flyers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT UNIQUE,
            thumbnail_url TEXT,
            valid_from TEXT,
            valid_to TEXT,
            pages_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY, -- EAN / Barcode
            name TEXT NOT NULL,
            category_id INTEGER,
            category_path TEXT,
            unit TEXT,
            unit_title TEXT,
            packaging TEXT,
            image_url TEXT,
            min_unit_price REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            chain_id TEXT,
            chain_name TEXT NOT NULL,
            price_type TEXT NOT NULL, -- NORMAL, DISCOUNTED
            amount REAL NOT NULL,
            unit_amount REAL,
            same_amount_everywhere INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
        CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category_id);
        CREATE INDEX IF NOT EXISTS idx_prices_prod ON prices(product_id);
        CREATE INDEX IF NOT EXISTS idx_prices_chain ON prices(chain_name);
        CREATE INDEX IF NOT EXISTS idx_shops_chain ON shops(chain_name);
        CREATE INDEX IF NOT EXISTS idx_shops_city ON shops(city);
        CREATE INDEX IF NOT EXISTS idx_flyers_chain ON flyers(chain_name);

        CREATE TABLE IF NOT EXISTS crawl_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            status TEXT,
            categories_count INTEGER DEFAULT 0,
            products_count INTEGER DEFAULT 0,
            prices_count INTEGER DEFAULT 0,
            message TEXT
        );
        """)
    conn.close()

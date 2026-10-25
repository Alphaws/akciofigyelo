import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Request, Query, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import init_db, get_db_connection
from crawler import run_full_crawler
from calculator import evaluate_shopping_list, search_products_for_query
from auth import (
    hash_password, verify_password, create_access_token, 
    verify_access_token, verify_google_id_token, GOOGLE_CLIENT_ID
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("akciofigyelo")

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    
    # Napi futtatás ütemezése éjjel 4:00-kor
    cron_hour = int(os.environ.get("CRAWL_CRON_HOUR", 4))
    scheduler.add_job(run_full_crawler, 'cron', hour=cron_hour, minute=0, id="daily_crawl")
    scheduler.start()
    logger.info(f"APScheduler elindult. Napi szinkronizáció ütemezve: {cron_hour}:00")

    # Ha még üres az adatbázis, indítsunk egy kezdeti adatgyűjtést a háttérben
    conn = get_db_connection()
    prod_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    if prod_count == 0:
        logger.info("Adatbázis üres, kezdeti crawler indítása a háttérben...")
        asyncio.create_task(run_full_crawler())

    yield
    scheduler.shutdown()

app = FastAPI(title="Akciófigyelő & Bevásárlólista Kalkulátor", lifespan=lifespan)

os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

class ShoppingItemModel(BaseModel):
    query: str
    quantity: float = 1.0
    unit: str = "db"

class ShoppingListRequest(BaseModel):
    shopping_list: Optional[str] = None
    items: Optional[List[ShoppingItemModel]] = None

class ParseListRequest(BaseModel):
    shopping_list: str

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str

class GoogleAuthRequest(BaseModel):
    credential: str

class UpdatePriceRequest(BaseModel):
    product_id: str
    chain_name: str
    amount: float
    price_type: Optional[str] = "NORMAL"
    note: Optional[str] = ""

class UpdateProductCategoryRequest(BaseModel):
    product_id: str
    main_category: str
    sub_category: str
    note: Optional[str] = ""

class CreateTaxonomyCategoryRequest(BaseModel):
    key: str
    title: str
    icon: Optional[str] = "fa-solid fa-box"
    sort_order: Optional[int] = 100

class UpdateTaxonomyCategoryRequest(BaseModel):
    title: str
    icon: Optional[str] = "fa-solid fa-box"
    sort_order: Optional[int] = 100

class CreateTaxonomySubcategoryRequest(BaseModel):
    main_key: str
    sub_key: str
    title: str
    sort_order: Optional[int] = 100

class UpdateTaxonomySubcategoryRequest(BaseModel):
    title: str
    sort_order: Optional[int] = 100

def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bejelentkezés szükséges a művelethez.")
    token = authorization.split(" ", 1)[1]
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Érvénytelen vagy lejárt munkamenet.")
    return payload

def get_current_admin(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    user = get_current_user(authorization)
    conn = get_db_connection()
    row = conn.execute("SELECT role FROM users WHERE id = ?", (user["sub"],)).fetchone()
    conn.close()
    if not row or row["role"] != "admin":
        raise HTTPException(status_code=403, detail="Csak adminisztrátor módosíthatja a kategória struktúrát.")
    return user

@app.get("/api/auth/config")
async def api_auth_config():
    return {
        "google_client_id": GOOGLE_CLIENT_ID or ""
    }

@app.post("/api/auth/register")
async def api_register(req: RegisterRequest):
    email = req.email.strip().lower()
    name = req.name.strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Érvénytelen e-mail cím.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="A jelszónak legalább 6 karakterből kell állnia.")

    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Ez az e-mail cím már regisztrálva van.")

    pwd_hash = hash_password(req.password)
    cur = conn.execute("""
        INSERT INTO users (email, name, password_hash, role)
        VALUES (?, ?, ?, 'editor')
    """, (email, name or email.split("@")[0], pwd_hash))
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    token = create_access_token(user_id, email, name, role="editor")
    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "name": name,
            "role": "editor"
        }
    }

@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    email = req.email.strip().lower()
    conn = get_db_connection()
    user = conn.execute("SELECT id, email, name, password_hash, role, avatar_url FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not user or not user["password_hash"] or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Hibás e-mail cím vagy jelszó.")

    token = create_access_token(user["id"], user["email"], user["name"], role=user["role"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "avatar_url": user["avatar_url"]
        }
    }

@app.post("/api/auth/google")
async def api_google_login(req: GoogleAuthRequest):
    g_info = await verify_google_id_token(req.credential)
    if not g_info:
        raise HTTPException(status_code=400, detail="Érvénytelen Google fiók azonosítás.")

    email = g_info["email"]
    name = g_info["name"]
    google_id = g_info["google_id"]
    avatar = g_info.get("avatar_url", "")

    conn = get_db_connection()
    user = conn.execute("SELECT id, email, name, role, avatar_url FROM users WHERE email = ? OR google_id = ?", (email, google_id)).fetchone()
    if user:
        user_id = user["id"]
        # Update google_id and avatar if missing
        conn.execute("UPDATE users SET google_id = ?, avatar_url = COALESCE(avatar_url, ?) WHERE id = ?", (google_id, avatar, user_id))
        conn.commit()
        role = user["role"]
        u_name = user["name"]
    else:
        cur = conn.execute("""
            INSERT INTO users (email, name, google_id, avatar_url, role)
            VALUES (?, ?, ?, ?, 'editor')
        """, (email, name, google_id, avatar))
        user_id = cur.lastrowid
        conn.commit()
        role = "editor"
        u_name = name

    conn.close()
    token = create_access_token(user_id, email, u_name, role=role)
    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "name": u_name,
            "role": role,
            "avatar_url": avatar
        }
    }

@app.get("/api/auth/me")
async def api_me(user: Dict[str, Any] = None, authorization: Optional[str] = Header(None)):
    current_u = get_current_user(authorization)
    conn = get_db_connection()
    row = conn.execute("SELECT id, email, name, role, avatar_url FROM users WHERE id = ?", (current_u["sub"],)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Felhasználó nem található.")
    return {"user": dict(row)}

@app.post("/api/products/price")
async def api_update_price(req: UpdatePriceRequest, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    conn = get_db_connection()

    # Ellenőrizzük a terméket
    product = conn.execute("SELECT id, name FROM products WHERE id = ?", (req.product_id,)).fetchone()
    if not product:
        conn.close()
        raise HTTPException(status_code=404, detail="Termék nem található.")

    # Meglévő ár keresése
    existing_price = conn.execute("""
        SELECT id, amount, price_type FROM prices 
        WHERE product_id = ? AND chain_name = ?
    """, (req.product_id, req.chain_name)).fetchone()

    old_amount = existing_price["amount"] if existing_price else None
    old_type = existing_price["price_type"] if existing_price else None
    action = "UPDATE_PRICE" if existing_price else "CREATE_PRICE"

    if existing_price:
        conn.execute("""
            UPDATE prices
            SET amount = ?, price_type = ?, unit_amount = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (req.amount, req.price_type, req.amount, existing_price["id"]))
    else:
        chain_id = f"{req.chain_name.lower()}-manual"
        conn.execute("""
            INSERT INTO prices (product_id, chain_id, chain_name, price_type, amount, unit_amount, same_amount_everywhere, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        """, (req.product_id, chain_id, req.chain_name, req.price_type, req.amount, req.amount))

    # Audit log bejegyzés létrehozása
    conn.execute("""
        INSERT INTO price_audit_logs 
        (user_id, user_email, user_name, action, product_id, product_name, chain_name, old_amount, new_amount, old_price_type, new_price_type, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user["sub"], user["email"], user["name"], action, 
        req.product_id, product["name"], req.chain_name, 
        old_amount, req.amount, old_type, req.price_type, req.note or ""
    ))

    # Min unit price újraszámolása a terméken
    min_price_row = conn.execute("SELECT MIN(amount) FROM prices WHERE product_id = ?", (req.product_id,)).fetchone()
    if min_price_row and min_price_row[0] is not None:
        conn.execute("UPDATE products SET min_unit_price = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (min_price_row[0], req.product_id))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": f"Ár sikeresen rögzítve ({req.chain_name}: {req.amount:,.0f} Ft). Módosítás naplózva.",
        "action": action
    }

@app.post("/api/products/category")
async def api_update_product_category(req: UpdateProductCategoryRequest, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    conn = get_db_connection()

    product = conn.execute("SELECT id, name, main_category, sub_category FROM products WHERE id = ?", (req.product_id,)).fetchone()
    if not product:
        conn.close()
        raise HTTPException(status_code=404, detail="Termék nem található.")

    from categories import get_taxonomy_tree_from_db
    tree = get_taxonomy_tree_from_db(conn)
    if req.main_category not in tree:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Érvénytelen főkategória: {req.main_category}")
    if req.sub_category not in tree[req.main_category].get("subs", {}):
        conn.close()
        raise HTTPException(status_code=400, detail=f"Érvénytelen alkategória: {req.sub_category}")

    old_main = product["main_category"]
    old_sub = product["sub_category"]

    conn.execute("""
        UPDATE products
        SET main_category = ?, sub_category = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (req.main_category, req.sub_category, req.product_id))

    # Audit log
    conn.execute("""
        INSERT INTO category_audit_logs
        (user_id, user_email, user_name, action, entity_id, entity_name, old_value, new_value, note)
        VALUES (?, ?, ?, 'UPDATE_PRODUCT_CATEGORY', ?, ?, ?, ?, ?)
    """, (
        user["sub"], user["email"], user["name"],
        req.product_id, product["name"],
        f"{old_main}/{old_sub}", f"{req.main_category}/{req.sub_category}",
        req.note or ""
    ))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": f"Termék kategóriája sikeresen módosítva: {tree[req.main_category]['title']} -> {tree[req.main_category]['subs'][req.sub_category]}",
        "main_category": req.main_category,
        "sub_category": req.sub_category
    }

# ==================== ADMIN TAXONOMY TREE MANAGEMENT ====================

@app.post("/api/admin/categories")
async def api_admin_create_category(req: CreateTaxonomyCategoryRequest, authorization: Optional[str] = Header(None)):
    admin = get_current_admin(authorization)
    conn = get_db_connection()

    key = req.key.strip().lower()
    title = req.title.strip()
    if not key or not title:
        conn.close()
        raise HTTPException(status_code=400, detail="Kategória kulcs és megnevezés megadása kötelező.")

    existing = conn.execute("SELECT key FROM taxonomy_categories WHERE key = ?", (key,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Ez a főkategória azonosító már létezik.")

    conn.execute("""
        INSERT INTO taxonomy_categories (key, title, icon, sort_order)
        VALUES (?, ?, ?, ?)
    """, (key, title, req.icon or "fa-solid fa-box", req.sort_order or 100))

    conn.execute("""
        INSERT INTO category_audit_logs
        (user_id, user_email, user_name, action, entity_id, entity_name, old_value, new_value, note)
        VALUES (?, ?, ?, 'CREATE_CATEGORY', ?, ?, NULL, ?, 'Új főkategória hozzáadva')
    """, (admin["sub"], admin["email"], admin["name"], key, title, title))

    conn.commit()
    conn.close()
    return {"status": "success", "message": f"'{title}' főkategória sikeresen létrehozva."}

@app.put("/api/admin/categories/{cat_key}")
async def api_admin_update_category(cat_key: str, req: UpdateTaxonomyCategoryRequest, authorization: Optional[str] = Header(None)):
    admin = get_current_admin(authorization)
    conn = get_db_connection()

    existing = conn.execute("SELECT key, title, icon, sort_order FROM taxonomy_categories WHERE key = ?", (cat_key,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Főkategória nem található.")

    conn.execute("""
        UPDATE taxonomy_categories
        SET title = ?, icon = ?, sort_order = ?
        WHERE key = ?
    """, (req.title.strip(), req.icon or "fa-solid fa-box", req.sort_order, cat_key))

    conn.execute("""
        INSERT INTO category_audit_logs
        (user_id, user_email, user_name, action, entity_id, entity_name, old_value, new_value, note)
        VALUES (?, ?, ?, 'UPDATE_CATEGORY', ?, ?, ?, ?, 'Főkategória módosítva')
    """, (admin["sub"], admin["email"], admin["name"], cat_key, req.title, existing["title"], req.title))

    conn.commit()
    conn.close()
    return {"status": "success", "message": "Főkategória sikeresen frissítve."}

@app.delete("/api/admin/categories/{cat_key}")
async def api_admin_delete_category(cat_key: str, authorization: Optional[str] = Header(None)):
    admin = get_current_admin(authorization)
    conn = get_db_connection()

    existing = conn.execute("SELECT key, title FROM taxonomy_categories WHERE key = ?", (cat_key,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Főkategória nem található.")

    # A kategóriában lévő termékeket áttesszük egyébbe
    conn.execute("UPDATE products SET main_category = 'egyeb', sub_category = 'egyeb' WHERE main_category = ?", (cat_key,))
    conn.execute("DELETE FROM taxonomy_subcategories WHERE main_key = ?", (cat_key,))
    conn.execute("DELETE FROM taxonomy_categories WHERE key = ?", (cat_key,))

    conn.execute("""
        INSERT INTO category_audit_logs
        (user_id, user_email, user_name, action, entity_id, entity_name, old_value, new_value, note)
        VALUES (?, ?, ?, 'DELETE_CATEGORY', ?, ?, ?, NULL, 'Főkategória törölve')
    """, (admin["sub"], admin["email"], admin["name"], cat_key, existing["title"], existing["title"]))

    conn.commit()
    conn.close()
    return {"status": "success", "message": f"'{existing['title']}' főkategória és alkategóriái törölve."}

@app.post("/api/admin/subcategories")
async def api_admin_create_subcategory(req: CreateTaxonomySubcategoryRequest, authorization: Optional[str] = Header(None)):
    admin = get_current_admin(authorization)
    conn = get_db_connection()

    main_key = req.main_key.strip().lower()
    sub_key = req.sub_key.strip().lower()
    title = req.title.strip()

    main_cat = conn.execute("SELECT key, title FROM taxonomy_categories WHERE key = ?", (main_key,)).fetchone()
    if not main_cat:
        conn.close()
        raise HTTPException(status_code=404, detail="A megadott főkategória nem található.")

    existing = conn.execute("SELECT sub_key FROM taxonomy_subcategories WHERE main_key = ? AND sub_key = ?", (main_key, sub_key)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Ez az alkategória azonosító már létezik a főkategóriában.")

    conn.execute("""
        INSERT INTO taxonomy_subcategories (main_key, sub_key, title, sort_order)
        VALUES (?, ?, ?, ?)
    """, (main_key, sub_key, title, req.sort_order or 100))

    conn.execute("""
        INSERT INTO category_audit_logs
        (user_id, user_email, user_name, action, entity_id, entity_name, old_value, new_value, note)
        VALUES (?, ?, ?, 'CREATE_SUBCATEGORY', ?, ?, NULL, ?, 'Új alkategória hozzáadva')
    """, (admin["sub"], admin["email"], admin["name"], f"{main_key}/{sub_key}", title, title))

    conn.commit()
    conn.close()
    return {"status": "success", "message": f"'{title}' alkategória sikeresen hozzáadva."}

@app.put("/api/admin/subcategories/{main_key}/{sub_key}")
async def api_admin_update_subcategory(main_key: str, sub_key: str, req: UpdateTaxonomySubcategoryRequest, authorization: Optional[str] = Header(None)):
    admin = get_current_admin(authorization)
    conn = get_db_connection()

    existing = conn.execute("SELECT title, sort_order FROM taxonomy_subcategories WHERE main_key = ? AND sub_key = ?", (main_key, sub_key)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Alkategória nem található.")

    conn.execute("""
        UPDATE taxonomy_subcategories
        SET title = ?, sort_order = ?
        WHERE main_key = ? AND sub_key = ?
    """, (req.title.strip(), req.sort_order, main_key, sub_key))

    conn.execute("""
        INSERT INTO category_audit_logs
        (user_id, user_email, user_name, action, entity_id, entity_name, old_value, new_value, note)
        VALUES (?, ?, ?, 'UPDATE_SUBCATEGORY', ?, ?, ?, ?, 'Alkategória módosítva')
    """, (admin["sub"], admin["email"], admin["name"], f"{main_key}/{sub_key}", req.title, existing["title"], req.title))

    conn.commit()
    conn.close()
    return {"status": "success", "message": "Alkategória sikeresen frissítve."}

@app.delete("/api/admin/subcategories/{main_key}/{sub_key}")
async def api_admin_delete_subcategory(main_key: str, sub_key: str, authorization: Optional[str] = Header(None)):
    admin = get_current_admin(authorization)
    conn = get_db_connection()

    existing = conn.execute("SELECT title FROM taxonomy_subcategories WHERE main_key = ? AND sub_key = ?", (main_key, sub_key)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Alkategória nem található.")

    # A törölt alkategóriájú termékeket áttesszük az egyébbe
    conn.execute("UPDATE products SET sub_category = 'egyeb' WHERE main_category = ? AND sub_category = ?", (main_key, sub_key))
    conn.execute("DELETE FROM taxonomy_subcategories WHERE main_key = ? AND sub_key = ?", (main_key, sub_key))

    conn.execute("""
        INSERT INTO category_audit_logs
        (user_id, user_email, user_name, action, entity_id, entity_name, old_value, new_value, note)
        VALUES (?, ?, ?, 'DELETE_SUBCATEGORY', ?, ?, ?, NULL, 'Alkategória törölve')
    """, (admin["sub"], admin["email"], admin["name"], f"{main_key}/{sub_key}", existing["title"], existing["title"]))

    conn.commit()
    conn.close()
    return {"status": "success", "message": f"'{existing['title']}' alkategória törölve."}

@app.get("/api/price-audit-logs")
async def api_audit_logs(
    product_id: Optional[str] = None, 
    limit: int = Query(50, ge=1, le=200),
    authorization: Optional[str] = Header(None)
):
    # Napló megtekintése bejelentkezett felhasználóknak (vagy nyilvánosan az átláthatóságért)
    conn = get_db_connection()
    params = []
    where = []
    if product_id:
        where.append("product_id = ?")
        params.append(product_id)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT id, user_email, user_name, action, product_id, product_name, chain_name, old_amount, new_amount, old_price_type, new_price_type, note, created_at
        FROM price_audit_logs
        {where_sql}
        ORDER BY id DESC
        LIMIT ?
    """
    rows = conn.execute(sql, params + [limit]).fetchall()
    conn.close()
    return {"logs": [dict(r) for r in rows]}

@app.post("/api/parse-list")
async def api_parse_list(req: ParseListRequest):
    from calculator import parse_shopping_list
    items = parse_shopping_list(req.shopping_list)
    return {"items": items}

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    conn = get_db_connection()
    stats = {
        "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "prices": conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0],
        "chains": [r["name"] for r in conn.execute("SELECT DISTINCT name FROM chain_stores ORDER BY name").fetchall()],
        "last_crawl": conn.execute("SELECT * FROM crawl_logs ORDER BY id DESC LIMIT 1").fetchone()
    }
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "stats": stats})

@app.get("/api/stats")
async def get_stats():
    conn = get_db_connection()
    stats = {
        "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "prices": conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0],
        "chains": [r["name"] for r in conn.execute("SELECT DISTINCT name FROM chain_stores ORDER BY name").fetchall()],
        "last_crawl": dict(conn.execute("SELECT * FROM crawl_logs ORDER BY id DESC LIMIT 1").fetchone() or {})
    }
    conn.close()
    return stats

@app.post("/api/sync")
async def trigger_sync(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_full_crawler)
    return {"status": "started", "message": "Napi árak szinkronizálása a háttérben elindult."}

@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=2)):
    results = search_products_for_query(q)
    return {"query": q, "results": results}

import math
import json

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 2)

@app.get("/api/categories")
async def api_categories():
    from categories import get_taxonomy_tree_from_db
    conn = get_db_connection()
    taxonomy_tree = get_taxonomy_tree_from_db(conn)

    # Statisztika lekérése kategóriánként és alkategóriánként
    stats_rows = conn.execute("""
        SELECT main_category, sub_category, COUNT(*) as cnt
        FROM products
        WHERE main_category IS NOT NULL
        GROUP BY main_category, sub_category
    """).fetchall()
    conn.close()

    counts = {}
    main_totals = {}
    for r in stats_rows:
        mc = r["main_category"]
        sc = r["sub_category"]
        cnt = r["cnt"]
        counts.setdefault(mc, {})[sc] = cnt
        main_totals[mc] = main_totals.get(mc, 0) + cnt

    result = []
    for mc_key, mc_data in taxonomy_tree.items():
        sub_list = []
        for sc_key, sc_title in mc_data["subs"].items():
            sc_count = counts.get(mc_key, {}).get(sc_key, 0)
            sub_list.append({
                "key": sc_key,
                "title": sc_title,
                "count": sc_count
            })
        
        result.append({
            "key": mc_key,
            "title": mc_data["title"],
            "icon": mc_data["icon"],
            "sort_order": mc_data.get("sort_order", 0),
            "total_count": main_totals.get(mc_key, 0),
            "subs": sub_list
        })

    return {"categories": result}

@app.get("/api/products-catalog")
async def api_products_catalog(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    q: Optional[str] = None,
    chain: Optional[str] = None,
    main_category: Optional[str] = None,
    sub_category: Optional[str] = None,
    category: Optional[str] = None
):
    conn = get_db_connection()
    where = []
    params = []

    if q:
        from calculator import normalize_text
        words = normalize_text(q).split()
        for w in words:
            where.append("NORMALIZE(p.name) LIKE ?")
            params.append(f"%{w}%")

    if chain:
        where.append("EXISTS (SELECT 1 FROM prices pr WHERE pr.product_id = p.id AND pr.chain_name = ?)")
        params.append(chain)

    if main_category:
        where.append("p.main_category = ?")
        params.append(main_category)

    if sub_category:
        where.append("p.sub_category = ?")
        params.append(sub_category)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    
    count_sql = f"SELECT COUNT(*) FROM products p {where_sql}"
    total = conn.execute(count_sql, params).fetchone()[0]

    offset = (page - 1) * page_size
    fetch_sql = f"""
        SELECT p.id, p.name, p.category_path, p.main_category, p.sub_category, p.unit, p.unit_title, p.packaging, p.image_url, p.min_unit_price
        FROM products p
        {where_sql}
        ORDER BY p.name ASC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(fetch_sql, params + [page_size, offset]).fetchall()

    from categories import get_taxonomy_tree_from_db
    taxonomy_tree = get_taxonomy_tree_from_db(conn)
    items = []
    for r in rows:
        pid = r["id"]
        prices = conn.execute("""
            SELECT chain_name, price_type, amount, unit_amount
            FROM prices
            WHERE product_id = ?
            ORDER BY amount ASC
        """, (pid,)).fetchall()

        chain_prices = {}
        for pr in prices:
            cname = pr["chain_name"]
            if cname not in chain_prices or pr["amount"] < chain_prices[cname]["amount"]:
                chain_prices[cname] = {
                    "chain": cname,
                    "price_type": pr["price_type"],
                    "amount": pr["amount"],
                    "unit_amount": pr["unit_amount"]
                }

        mc = r["main_category"]
        sc = r["sub_category"]
        mc_title = taxonomy_tree.get(mc, {}).get("title", mc or "")
        sc_title = taxonomy_tree.get(mc, {}).get("subs", {}).get(sc, sc or "")

        items.append({
            "id": pid,
            "name": r["name"],
            "category_path": r["category_path"],
            "main_category": mc,
            "sub_category": sc,
            "main_category_title": mc_title,
            "sub_category_title": sc_title,
            "unit": r["unit"],
            "unit_title": r["unit_title"],
            "packaging": r["packaging"],
            "image_url": r["image_url"],
            "min_unit_price": r["min_unit_price"],
            "chain_prices": chain_prices
        })
    conn.close()

    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "products": items
    }

@app.get("/api/shops")
async def api_shops(
    city: Optional[str] = None,
    chain: Optional[str] = None,
    user_lat: Optional[float] = None,
    user_lon: Optional[float] = None,
    limit: int = Query(50, ge=1, le=500)
):
    conn = get_db_connection()
    where = []
    params = []
    if city:
        where.append("LOWER(city) LIKE ?")
        params.append(f"%{city.lower()}%")
    if chain:
        where.append("chain_name = ?")
        params.append(chain)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT uuid, chain_id, chain_name, postal_code, city, address, latitude, longitude, opening_time
        FROM shops
        {where_sql}
        ORDER BY city ASC, address ASC
    """
    rows = conn.execute(sql, params).fetchall()
    
    shops_list = []
    for r in rows:
        s = dict(r)
        if user_lat is not None and user_lon is not None and s.get("latitude") and s.get("longitude"):
            s["distance_km"] = haversine_km(user_lat, user_lon, s["latitude"], s["longitude"])
        else:
            s["distance_km"] = None
        shops_list.append(s)

    if user_lat is not None and user_lon is not None:
        shops_list.sort(key=lambda x: (x["distance_km"] is None, x["distance_km"] or 9999))

    conn.close()
    return {"count": len(shops_list), "shops": shops_list[:limit]}

def extract_validity_period(title: str, url: str = "", updated_at: str = "") -> tuple[str, str]:
    import re
    from datetime import datetime, timedelta
    text = f"{title} {url}"
    # Minta 1: év.hó.nap - hó.nap
    m1 = re.search(r'(\d{4})[\.\s\-]+(\d{1,2})[\.\-](\d{1,2})\s*[-–]\s*(?:(\d{1,2})[\.\-])?(\d{1,2})', text)
    if m1:
        y, m1_m, d1, m2_m, d2 = m1.groups()
        m2 = m2_m if m2_m else m1_m
        end_date = f"{y}-{int(m2):02d}-{int(d2):02d}"
        return f"{y}.{int(m1_m):02d}.{int(d1):02d} – {y}.{int(m2):02d}.{int(d2):02d}", end_date
    
    # Minta 2: egyetlen kezdőnap (általában 6 nappal későbbi zárással)
    m2 = re.search(r'(\d{4})[\.\s\-]+(\d{1,2})[\.\-](\d{1,2})', text)
    if m2:
        y, m, d = m2.groups()
        try:
            start_dt = datetime.strptime(f"{y}-{int(m):02d}-{int(d):02d}", "%Y-%m-%d")
            end_date = (start_dt + timedelta(days=6)).strftime("%Y-%m-%d")
        except:
            end_date = f"{y}-{int(m):02d}-{int(d):02d}"
        return f"{y}.{int(m):02d}.{int(d):02d}-tól", end_date

    # Ha nincs feliratban dátum, a crawl időpontjához képest tekintjük érvényesnek 6 napig
    try:
        up_dt = datetime.strptime(updated_at[:10], "%Y-%m-%d")
        end_date = (up_dt + timedelta(days=6)).strftime("%Y-%m-%d")
    except:
        end_date = "2026-12-31"

    return "Aktuális heti akció", end_date

@app.get("/api/flyers")
async def api_flyers(chain: Optional[str] = None):
    conn = get_db_connection()
    sql = "SELECT id, chain_name, title, url, thumbnail_url, pages_json, updated_at FROM flyers"
    params = []
    if chain:
        sql += " WHERE chain_name = ?"
        params.append(chain)
    sql += " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    
    flyers = []
    for r in rows:
        item = dict(r)
        import html
        item["title"] = html.unescape(item.get("title") or "").replace(" - Akciós-Újság.hu", "").strip()
        val_text, end_d = extract_validity_period(item["title"], item.get("url") or "", item.get("updated_at") or "")
        item["validity"] = val_text
        item["end_date"] = end_d
        try:
            item["pages"] = json.loads(item.get("pages_json") or "[]")
        except:
            item["pages"] = []
        flyers.append(item)
    conn.close()

    # Vége dátum alapján csökkenő sorrend (legfrissebb / legtovább érvényes elöl), másodlagosan ID DESC
    flyers.sort(key=lambda x: (x.get("end_date") or "", x["id"]), reverse=True)

    return {"count": len(flyers), "flyers": flyers}

@app.post("/api/calculate")
async def api_calculate(req: ShoppingListRequest):
    if req.items is not None:
        items_dict = [it.model_dump() for it in req.items]
        result = evaluate_shopping_list(items_dict)
    else:
        result = evaluate_shopping_list(req.shopping_list or "")
    return result

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8097))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("server:app", host=host, port=port, reload=True)

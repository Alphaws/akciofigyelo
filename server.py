import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import init_db, get_db_connection
from crawler import run_full_crawler
from calculator import evaluate_shopping_list, search_products_for_query

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

@app.get("/api/products-catalog")
async def api_products_catalog(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    q: Optional[str] = None,
    chain: Optional[str] = None,
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

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    
    count_sql = f"SELECT COUNT(*) FROM products p {where_sql}"
    total = conn.execute(count_sql, params).fetchone()[0]

    offset = (page - 1) * page_size
    fetch_sql = f"""
        SELECT p.id, p.name, p.category_path, p.unit, p.unit_title, p.packaging, p.image_url, p.min_unit_price
        FROM products p
        {where_sql}
        ORDER BY p.name ASC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(fetch_sql, params + [page_size, offset]).fetchall()

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

        items.append({
            "id": pid,
            "name": r["name"],
            "category_path": r["category_path"],
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
        try:
            item["pages"] = json.loads(item.get("pages_json") or "[]")
        except:
            item["pages"] = []
        flyers.append(item)
    conn.close()
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

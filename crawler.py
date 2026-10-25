import asyncio
import logging
import httpx
import time
from datetime import datetime
from database import get_db_connection

logger = logging.getLogger("crawler")
logger.setLevel(logging.INFO)

API_BASE = "https://arfigyelo.gvh.hu/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

async def fetch_chain_stores(client: httpx.AsyncClient):
    chain_map = {}
    try:
        resp = await client.get(f"{API_BASE}/chain-stores")
        if resp.status_code == 200:
            data = resp.json().get("chainStores", [])
            conn = get_db_connection()
            with conn:
                for c in data:
                    cid = c.get("uuid")
                    cname = c.get("name")
                    chain_map[cid] = cname
                    conn.execute("""
                        INSERT OR REPLACE INTO chain_stores (id, name, image_url)
                        VALUES (?, ?, ?)
                    """, (cid, cname, c.get("imageUrl")))
            conn.close()
            logger.info(f"Bolt láncok frissítve: {len(data)} db")
    except Exception as e:
        logger.error(f"Hiba a boltláncok lekérésekor: {e}")
    return chain_map

async def fetch_shops(client: httpx.AsyncClient, chain_map: dict):
    try:
        resp = await client.get(f"{API_BASE}/shops")
        if resp.status_code == 200:
            data = resp.json().get("shops", [])
            conn = get_db_connection()
            with conn:
                conn.execute("DELETE FROM shops")
                for s in data:
                    uuid = s.get("uuid")
                    chain_id = s.get("chainStoreUuid")
                    chain_name = chain_map.get(chain_id, "Egyéb")
                    postal_code = s.get("postalCode")
                    city = s.get("city")
                    address = s.get("address")
                    loc = s.get("location") or {}
                    lat = loc.get("latitude")
                    lon = loc.get("longitude")
                    op = s.get("openingTime", "")
                    conn.execute("""
                        INSERT OR REPLACE INTO shops (uuid, chain_id, chain_name, postal_code, city, address, latitude, longitude, opening_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (uuid, chain_id, chain_name, postal_code, city, address, lat, lon, op))
            conn.close()
            logger.info(f"Üzletek frissítve: {len(data)} db bolt címe és GPS koordinátája mentve.")
            return len(data)
    except Exception as e:
        logger.error(f"Hiba a boltok letöltésekor: {e}")
    return 0

async def fetch_prima_offers_and_shops(client: httpx.AsyncClient):
    import re, json, urllib.request
    prima_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    # 1. Príma / CBA üzletek letöltése és mentése
    try:
        req = urllib.request.Request("https://www.prima.hu/uzletlista/", headers=prima_headers)
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore')
        matches = re.findall(r'\{[^{}]*\"A_VAROS\"[^{}]*\}', html)
        conn = get_db_connection()
        with conn:
            for m in matches:
                try:
                    s = json.loads(m)
                    uid = "prima-" + str(s.get("P_ID", ""))
                    pname = s.get("P_NAME", "")
                    chain_name = "Príma" if "príma" in pname.lower() or "prima" in pname.lower() else "CBA"
                    city = s.get("A_VAROS", "").strip()
                    postal_code = str(s.get("A_IRSZ", "")).strip()
                    address = s.get("A_CIM", "").strip()
                    lat = float(s.get("PS_GPS_COORDS_LAT")) if s.get("PS_GPS_COORDS_LAT") else None
                    lon = float(s.get("PS_GPS_COORDS_LNG")) if s.get("PS_GPS_COORDS_LNG") else None
                    
                    op = ""
                    if s.get("PS_OPEN_FROM_1") and s.get("PS_OPEN_TO_1"):
                        f1, t1 = str(s.get("PS_OPEN_FROM_1")), str(s.get("PS_OPEN_TO_1"))
                        op = f"H-P: {f1[:-2]}:{f1[-2:]}-{t1[:-2]}:{t1[-2:]}"

                    conn.execute("""
                        INSERT OR REPLACE INTO shops (uuid, chain_id, chain_name, postal_code, city, address, latitude, longitude, opening_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (uid, "prima-chain", chain_name, postal_code, city, address, lat, lon, op))
                except Exception:
                    pass
        conn.close()
        logger.info(f"Príma & CBA üzletek sikeresen feldolgozva: {len(matches)} db.")
    except Exception as e:
        logger.error(f"Hiba a Príma üzletek letöltésekor: {e}")

    # 2. Príma Aktuális Ajánlataink (szórólapok/akciók) letöltése
    try:
        req = urllib.request.Request("https://www.prima.hu/aktualis-ajanlataink/", headers=prima_headers)
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore')
        # Eredeti nagy felbontású képek
        imgs = re.findall(r'https?://www\.prima\.hu/wp-content/uploads/[0-9]{4}/[0-9]{2}/[^\'\"\s]+(?<!-[0-9]{3}x[0-9]{3})(?<!-[0-9]{4}x[0-9]{3})\.(?:jpg|jpeg|png|webp)', html)
        offer_imgs = [i for i in sorted(list(set(imgs))) if not any(x in i for x in ['logo', 'icon', 'favicon', 'szechenyi', 'bg1'])]

        if offer_imgs:
            conn = get_db_connection()
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO flyers (chain_name, title, url, thumbnail_url, pages_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, ("Príma", "Príma Aktuális Ajánlataink (Kiemelt Heti Akciók)", "https://www.prima.hu/aktualis-ajanlataink/", offer_imgs[0], json.dumps(offer_imgs)))
            conn.close()
            logger.info(f"Príma aktuális ajánlatok katalógus mentve: {len(offer_imgs)} oldal.")
    except Exception as e:
        logger.error(f"Hiba a Príma ajánlatok letöltésekor: {e}")

async def fetch_flyers(client: httpx.AsyncClient):
    import re, json, html
    try:
        resp = await client.get("https://akcios-ujsag.hu/", headers=HEADERS, timeout=15.0)
        if resp.status_code == 200:
            page_html = resp.text
            flyer_urls = set(re.findall(r'href=[\'\"](https?://[^\'\"]+/akcios-ujsagok/[^\'\"]+)[\'\"]', page_html, re.IGNORECASE))
            valid_urls = [u for u in flyer_urls if not u.lower().endswith('/feed/')]

            conn = get_db_connection()
            saved_count = 0
            with conn:
                for url in valid_urls[:35]: # Friss legfontosabb újságok
                    slug = url.rstrip('/').split('/')[-1]
                    chain = "Egyéb"
                    for c in ['aldi', 'lidl', 'spar', 'penny', 'tesco', 'auchan', 'rossmann', 'dm', 'mueller', 'metro', 'cba']:
                        if c in slug:
                            chain = c.capitalize()
                            break

                    # Nézzük meg a belső lapozó oldalait
                    try:
                        f_resp = await client.get(url, timeout=10.0)
                        if f_resp.status_code == 200:
                            f_html = f_resp.text
                            title_m = re.search(r'<title>(.*?)</title>', f_html)
                            raw_title = title_m.group(1) if title_m else slug
                            title = html.unescape(raw_title).replace(" - Akciós-Újság.hu", "").strip()
                            
                            imgs = re.findall(r'(https?://akcios-ujsag\.hu/uploads/[^\'\"\s]+\.(?:webp|jpg|jpeg|png))', f_html)
                            pages = sorted(list(set([i for i in imgs if '_page-' in i or 'page' in i])))
                            thumb = pages[0] if pages else (imgs[0] if imgs else None)

                            conn.execute("""
                                INSERT OR REPLACE INTO flyers (chain_name, title, url, thumbnail_url, pages_json, updated_at)
                                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                            """, (chain, title, url, thumb, json.dumps(pages)))
                            saved_count += 1

                            # --- TERMÉKEK ÉS ÁRAK KINYERÉSE AZ ÚJSÁG SZÖVEGÉBŐL ---
                            unescaped_text = html.unescape(f_html)
                            li_pattern = re.compile(
                                r'<li>([^<>\n]+?)\s*(?:–|-)\s*(\d+[\s\.]?\d*)\s*Ft(?:/([a-zA-Z\.]+))?(?:[^<>]*(?:<strong>.*?</strong>)?(?:\s*\(eredeti ár:\s*(\d+[\s\.]?\d*)\s*Ft)?.*?)?</li>',
                                re.IGNORECASE
                            )
                            for m in li_pattern.finditer(unescaped_text):
                                p_name = ' '.join(m.group(1).strip().strip(',;:').split())
                                p_price = float(m.group(2).replace(' ', '').replace('.', ''))
                                p_unit = m.group(3) or 'db'
                                p_orig = float(m.group(4).replace(' ', '').replace('.', '')) if m.group(4) else None

                                if len(p_name) > 2 and len(p_name) < 70 and not any(skip in p_name.lower() for skip in ['eredeti', 'akció', 'oldal', 'érvényes', 'zöldség-gyümölcs', 'hús és']):
                                    # Egyedi ID generálás az újságos akcióhoz
                                    import hashlib
                                    flyer_pid = f"flyer-{hashlib.md5((chain + '_' + p_name).encode()).hexdigest()[:12]}"
                                    
                                    from categories import resolve_product_categories
                                    main_c, sub_c = resolve_product_categories(p_name, f"akcios_ujsag/{chain.lower()}")

                                    conn.execute("""
                                        INSERT OR REPLACE INTO products (id, name, category_path, main_category, sub_category, unit, unit_title, packaging, image_url, min_unit_price, updated_at)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                                    """, (flyer_pid, p_name, f"akcios_ujsag/{chain.lower()}", main_c, sub_c, p_unit, "db", "1", thumb, p_price))

                                    conn.execute("""
                                        INSERT INTO prices (product_id, chain_id, chain_name, price_type, amount, unit_amount, same_amount_everywhere, updated_at)
                                        VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                                    """, (flyer_pid, f"{chain.lower()}-flyer", chain, "DISCOUNTED", p_price, p_price))
                    except Exception as fe:
                        pass
            conn.close()
            logger.info(f"Akciós újságok frissítve: {saved_count} db lapozható újság feldolgozva.")
            return saved_count
    except Exception as e:
        logger.error(f"Hiba az akciós újságok letöltésekor: {e}")
    return 0

async def fetch_categories(client: httpx.AsyncClient):
    leaf_categories = []
    try:
        resp = await client.get(f"{API_BASE}/categories")
        if resp.status_code == 200:
            cats = resp.json().get("categories", [])
            conn = get_db_connection()
            with conn:
                def walk(items, parent_id=None):
                    for item in items:
                        sub = item.get("categoryNodes", [])
                        cid = item.get("id")
                        cname = item.get("name")
                        cpath = item.get("path")
                        conn.execute("""
                            INSERT OR REPLACE INTO categories (id, name, path, parent_id)
                            VALUES (?, ?, ?, ?)
                        """, (cid, cname, cpath, parent_id))
                        if not sub:
                            leaf_categories.append({"id": cid, "name": cname, "path": cpath})
                        else:
                            walk(sub, cid)
                walk(cats)
            conn.close()
            logger.info(f"Kategóriák frissítve. Végkategóriák: {len(leaf_categories)} db")
    except Exception as e:
        logger.error(f"Hiba a kategóriák lekérésekor: {e}")
    return leaf_categories

async def crawl_category(client: httpx.AsyncClient, cat: dict, semaphore: asyncio.Semaphore):
    cid = cat["id"]
    async with semaphore:
        for attempt in range(3):
            try:
                resp = await client.get(f"{API_BASE}/products-by-category/{cid}", timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("products", [])
                elif resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                await asyncio.sleep(1)
        return []

async def run_full_crawler():
    logger.info("Napi árak és akciók szinkronizálása indult...")
    start_time = datetime.now()
    conn = get_db_connection()
    log_id = None
    with conn:
        cur = conn.execute("INSERT INTO crawl_logs (status, message) VALUES (?, ?)", ("running", "Adatgyűjtés folyamatban..."))
        log_id = cur.lastrowid
    conn.close()

    total_products = 0
    total_prices = 0

    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        chain_map = await fetch_chain_stores(client)
        await fetch_shops(client, chain_map)
        categories = await fetch_categories(client)

        semaphore = asyncio.Semaphore(5) # Barátságos 5 párhuzamos lekérés
        tasks = [crawl_category(client, cat, semaphore) for cat in categories]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        conn = get_db_connection()
        with conn:
            # Csak a korábbi árakat töröljük a friss adatok betöltése előtt
            conn.execute("DELETE FROM prices")
            
            for cat_res in results:
                if isinstance(cat_res, Exception) or not cat_res:
                    continue
                for p in cat_res:
                    pid = str(p.get("id"))
                    pname = p.get("name", "").strip()
                    cat_path = p.get("categoryPath")
                    unit = p.get("unit")
                    unit_title = p.get("unitTitle")
                    packaging = p.get("packaging")
                    img = p.get("imageUrl")
                    min_unit_price = p.get("minUnitPrice")

                    from categories import resolve_product_categories
                    main_c, sub_c = resolve_product_categories(pname, cat_path or "")

                    conn.execute("""
                        INSERT OR REPLACE INTO products (id, name, category_path, main_category, sub_category, unit, unit_title, packaging, image_url, min_unit_price, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (pid, pname, cat_path, main_c, sub_c, unit, unit_title, packaging, img, min_unit_price))
                    total_products += 1

                    for store in p.get("pricesOfChainStores", []):
                        chain_id = store.get("id")
                        chain_name = store.get("name")
                        for pr in store.get("prices", []):
                            price_type = pr.get("type", "NORMAL")
                            amount = pr.get("amount")
                            unit_amount = pr.get("unitAmount")
                            same_everywhere = 1 if pr.get("sameAmountEverywhere", True) else 0

                            if amount is not None:
                                conn.execute("""
                                    INSERT INTO prices (product_id, chain_id, chain_name, price_type, amount, unit_amount, same_amount_everywhere, updated_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                                """, (pid, chain_id, chain_name, price_type, amount, unit_amount, same_everywhere))
                                total_prices += 1

        # Az akciós újságok és a Príma akciók a GVH szinkronizáció UTÁN fussanak le, hogy az áraik megmaradjanak!
        await fetch_flyers(client)
        await fetch_prima_offers_and_shops(client)

        conn = get_db_connection()
        with conn:
            conn.execute("""
                UPDATE crawl_logs
                SET finished_at = CURRENT_TIMESTAMP, status = ?, categories_count = ?, products_count = ?, prices_count = ?, message = ?
                WHERE id = ?
            """, ("success", len(categories), total_products, total_prices, "Sikeres szinkronizáció", log_id))
        conn.close()

    logger.info(f"Szinkronizáció kész! Termékek: {total_products}, Árak: {total_prices}")
    return {"categories": len(categories), "products": total_products, "prices": total_prices}

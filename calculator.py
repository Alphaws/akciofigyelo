import re
from typing import List, Dict, Any, Optional
from database import get_db_connection

def normalize_text(text: str) -> str:
    text = text.lower()
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ö': 'o', 'ő': 'o',
        'ú': 'u', 'ü': 'u', 'ű': 'u', 'ä': 'a', 'ë': 'e'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return ' '.join(text.split())

def parse_shopping_list(raw_text: str) -> List[Dict[str, Any]]:
    """
    Kinyeri a tételeket és mennyiségeket szöveges sorokból.
    Támogatja:
    - 2 kg alma
    - 3 l tej 2.8
    - 10 db tojas / 10db tojas
    - alma 2 kg
    - 3x sor
    - 2 trappista sajt
    """
    items = []
    lines = raw_text.strip().split("\n")
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        # Csak a lista eleji bulletjeleket szedjük le: -, *, •
        line = re.sub(r'^[\-\*\•\s]+', '', line)
        
        qty = 1.0
        unit = "db"
        query = line

        # Elején 'x'-szel: '3x sör'
        m_front_num_only = re.match(r'^(\d+([\.,]\d+)?)\s*x\s*(.*)$', line, re.IGNORECASE)
        # Elején számmal és opcionális mértékegységgel: '2 kg alma', '10 db tojas', '2 trappista sajt'
        m_front = re.match(r'^(\d+([\.,]\d+)?)\s*(kg|dkg|g|l|liter|dl|ml|db|csomag|doboz|x)?\s+(.*)$', line, re.IGNORECASE)
        # Végén mértékegységgel: 'alma 2 kg', 'tojas 10 db'
        m_back = re.search(r'^(.*?)\s+(\d+([\.,]\d+)?)\s*(kg|dkg|g|l|liter|dl|ml|db|csomag|doboz|x)$', line, re.IGNORECASE)

        if m_front_num_only:
            qty = float(m_front_num_only.group(1).replace(",", "."))
            unit = "db"
            query = m_front_num_only.group(3).strip()
        elif m_front:
            qty = float(m_front.group(1).replace(",", "."))
            unit = (m_front.group(3) or "db").lower()
            if unit == "liter": unit = "l"
            if unit == "x": unit = "db"
            query = m_front.group(4).strip()
        elif m_back:
            query = m_back.group(1).strip()
            qty = float(m_back.group(2).replace(",", "."))
            unit = (m_back.group(4) or "db").lower()
            if unit == "liter": unit = "l"
            if unit == "x": unit = "db"

        if query:
            items.append({
                "original": raw_line.strip(),
                "query": query,
                "quantity": qty,
                "unit": unit
            })
    return items

def search_products_for_query(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    norm_words = normalize_text(query).split()
    if not norm_words:
        conn.close()
        return []

    # Keresés KIZÁRÓLAG a termék nevében (NORMALIZE(p.name))
    where_clauses = []
    params = []
    for nw in norm_words:
        where_clauses.append("NORMALIZE(p.name) LIKE ?")
        params.append(f"%{nw}%")

    sql = f"""
    SELECT p.id, p.name, p.category_path, p.unit, p.unit_title, p.packaging, p.image_url, p.min_unit_price
    FROM products p
    WHERE {" AND ".join(where_clauses)}
    ORDER BY p.min_unit_price ASC
    LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()

    result = []
    for r in rows:
        pid = r["id"]
        # Árak boltonként
        price_rows = conn.execute("""
            SELECT chain_name, price_type, amount, unit_amount
            FROM prices
            WHERE product_id = ?
            ORDER BY amount ASC
        """, (pid,)).fetchall()

        chain_prices = {}
        for pr in price_rows:
            cname = pr["chain_name"]
            # Ha van DISCOUNTED és NORMAL is, a legkisebbet vegyük
            if cname not in chain_prices or pr["amount"] < chain_prices[cname]["amount"]:
                chain_prices[cname] = {
                    "chain": cname,
                    "price_type": pr["price_type"],
                    "amount": pr["amount"],
                    "unit_amount": pr["unit_amount"]
                }

        result.append({
            "id": pid,
            "name": r["name"],
            "unit": r["unit"],
            "unit_title": r["unit_title"],
            "packaging": r["packaging"],
            "image_url": r["image_url"],
            "min_unit_price": r["min_unit_price"],
            "chain_prices": chain_prices
        })
    conn.close()
    return result

import math

def calculate_item_cost(req_qty: float, req_unit: str, prod_unit: Optional[str], packaging: Optional[str], amount: float, unit_amount: Optional[float]):
    try:
        pkg_size = float(packaging) if packaging else 1.0
    except (ValueError, TypeError):
        pkg_size = 1.0
    if pkg_size <= 0:
        pkg_size = 1.0

    prod_u = (prod_unit or "").lower()
    req_u = (req_unit or "db").lower()

    # 1. Ha a termék db-os kiszerelésű (pl. tojás: packaging='10' -> 10 db/doboz)
    if prod_u == "db":
        if req_u == "db":
            packs_needed = math.ceil(req_qty / pkg_size)
            total = packs_needed * amount
            note = f"{packs_needed} db doboz ({int(pkg_size)} db/csom)" if pkg_size > 1 else ""
            return total, packs_needed, note
        elif req_u in ["csomag", "doboz"]:
            total = req_qty * amount
            note = f"{req_qty} csomag"
            return total, req_qty, note

    # 2. Ha tömeg (kg, dkg, g):
    weight_multipliers = {"kg": 1.0, "dkg": 0.01, "g": 0.001}
    if prod_u == "kg":
        if req_u in weight_multipliers:
            req_kg = req_qty * weight_multipliers[req_u]
            if unit_amount and unit_amount > 0:
                total = req_kg * unit_amount
            else:
                total = (req_kg / pkg_size) * amount
            return total, req_kg, f"{req_kg:.2f} kg"
        elif req_u in ["db", "csomag", "doboz"]:
            total = req_qty * amount
            return total, req_qty, f"{req_qty} db ({pkg_size} kg/db)"

    # 3. Ha űrmérték (l, dl, ml):
    vol_multipliers = {"l": 1.0, "liter": 1.0, "dl": 0.1, "ml": 0.001}
    if prod_u == "l":
        if req_u in vol_multipliers:
            req_l = req_qty * vol_multipliers[req_u]
            if unit_amount and unit_amount > 0:
                total = req_l * unit_amount
            else:
                total = (req_l / pkg_size) * amount
            return total, req_l, f"{req_l:.2f} l"
        elif req_u in ["db", "csomag", "doboz"]:
            total = req_qty * amount
            return total, req_qty, f"{req_qty} db ({pkg_size} l/db)"

    # Alapeset
    total = req_qty * amount
    return total, req_qty, ""

def evaluate_shopping_list(raw_list_or_items):
    if isinstance(raw_list_or_items, list):
        parsed = []
        for it in raw_list_or_items:
            q = it.get("query", "").strip()
            if not q:
                continue
            qty = float(it.get("quantity", 1.0))
            unit = it.get("unit", "db")
            parsed.append({
                "original": f"{qty} {unit} {q}".strip(),
                "query": q,
                "quantity": qty,
                "unit": unit
            })
    else:
        parsed = parse_shopping_list(raw_list_or_items)

    if not parsed:
        return {"items": [], "stores": {}, "best_store": None, "cheapest_combination": None}

    # Lekérjük az összes ismert láncot
    conn = get_db_connection()
    chain_rows = conn.execute("SELECT DISTINCT chain_name FROM prices").fetchall()
    all_chains = [r["chain_name"] for r in chain_rows]
    conn.close()

    evaluated_items = []
    # Bolt -> {"total": 0, "found_count": 0, "missing": []}
    store_totals = {c: {"total": 0.0, "found_count": 0, "missing": [], "items": []} for c in all_chains}
    
    # Legolcsóbb kombináció (minden tételből az abszolút legolcsóbb boltban megvéve)
    best_item_picks = []

    for item in parsed:
        matches = search_products_for_query(item["query"], limit=10)
        
        item_eval = {
            "query": item["query"],
            "quantity": item["quantity"],
            "original": item["original"],
            "matched_products_count": len(matches),
            "store_prices": {}
        }

        cheapest_price = float("inf")
        cheapest_store = None
        cheapest_prod = None

        for chain in all_chains:
            # Megkeressük az adott láncban a legolcsóbb megfelelő terméket a teljes kért mennyiségre
            best_chain_total = float("inf")
            best_chain_prod = None

            for prod in matches:
                cp = prod["chain_prices"].get(chain)
                if cp:
                    item_cost, calc_qty, note = calculate_item_cost(
                        req_qty=item["quantity"],
                        req_unit=item["unit"],
                        prod_unit=prod.get("unit"),
                        packaging=prod.get("packaging"),
                        amount=cp["amount"],
                        unit_amount=cp.get("unit_amount")
                    )

                    if item_cost < best_chain_total:
                        best_chain_total = item_cost
                        best_chain_prod = {
                            "id": prod["id"],
                            "name": prod["name"],
                            "price": cp["amount"],
                            "unit_amount": cp.get("unit_amount"),
                            "price_type": cp["price_type"],
                            "image_url": prod["image_url"],
                            "packaging": prod.get("packaging"),
                            "note": note,
                            "total": round(item_cost)
                        }

            if best_chain_prod:
                item_eval["store_prices"][chain] = best_chain_prod
                store_totals[chain]["total"] += best_chain_prod["total"]
                store_totals[chain]["found_count"] += 1
                store_totals[chain]["items"].append(best_chain_prod)

                if best_chain_prod["total"] < cheapest_price:
                    cheapest_price = best_chain_prod["total"]
                    cheapest_store = chain
                    cheapest_prod = best_chain_prod
            else:
                store_totals[chain]["missing"].append(item["query"])

        if cheapest_store:
            best_item_picks.append({
                "query": item["query"],
                "store": cheapest_store,
                "product": cheapest_prod["name"],
                "unit_price": cheapest_prod["price"],
                "quantity": item["quantity"],
                "total": cheapest_prod["total"]
            })

        evaluated_items.append(item_eval)

    # Rendezés a legolcsóbb bolt szerint
    # Csak olyan boltokat rangsoroljunk, ahol legalább 1 tétel meglett
    ranked_stores = []
    total_requested = len(parsed)
    for c, data in store_totals.items():
        if data["found_count"] > 0:
            ranked_stores.append({
                "chain": c,
                "total": round(data["total"]),
                "found_count": data["found_count"],
                "missing_count": len(data["missing"]),
                "missing_items": data["missing"],
                "is_complete": data["found_count"] == total_requested
            })

    # Legtöbb tételt tartalmazó, legolcsóbb elöl
    ranked_stores.sort(key=lambda x: (-x["found_count"], x["total"]))

    best_combination_total = sum(p["total"] for p in best_item_picks)

    return {
        "requested_items_count": total_requested,
        "items": evaluated_items,
        "ranked_stores": ranked_stores,
        "best_combination": {
            "total": round(best_combination_total),
            "picks": best_item_picks
        }
    }

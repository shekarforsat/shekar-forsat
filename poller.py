"""پولر ۶۰ ثانیه‌ای دیوار — مدل دلال، ولی با دیتای واقعی به‌روز.

هر ۶۰ ثانیه جدیدترین آگهی‌های هر دسته را می‌گیرد، فقط توکن‌های تازه را
پردازش می‌کند، با موتور engine.py امتیاز می‌دهد و در SQLite ذخیره می‌کند.
Endpoint: POST /v8/postlist/w/search (وب‌سایت رسمی دیوار — بدون لاگین)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone

from engine import Ad, BaselineStore, fa_digits_to_int, score_ad, TIER_FA

API = "https://api.divar.ir/v8/postlist/w/search"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
DB = os.environ.get("DEALS_DB", "/home/hatch/workspace/divar-deals/deals.db")

CITIES = {
    "1": "تهران", "2": "کرج", "3": "مشهد", "4": "اصفهان", "5": "تبریز",
    "6": "شیراز", "7": "اهواز", "8": "قم", "9": "کرمانشاه", "10": "ارومیه",
    "12": "رشت", "13": "کرمان", "16": "یزد", "18": "بندرعباس", "11": "زاهدان",
    "14": "همدان", "22": "ساری", "21": "گرگان", "19": "قزوین", "15": "اراک",
    "20": "زنجان", "28": "سنندج", "27": "خرم‌آباد", "32": "ایلام", "25": "بوشهر",
    "34": "بیرجند", "36": "شهرکرد", "38": "یاسوج", "35": "سمنان", "39": "بجنورد",
    "17": "اردبیل",
}  # id دیوار -> نام شهر: هر ۳۱ مرکز استان (از /v8/places/cities)
CATEGORIES = ["cars", "motorcycles", "mobile-phones",
              "residential-sell", "residential-rent",
              "commercial-sell", "commercial-rent"]
# نگاشت دستهٔ دیوار -> دستهٔ موتور
CAT_MAP = {"cars": "car", "motorcycles": "motorcycle", "mobile-phones": "mobile",
           "residential-sell": "house_sell", "residential-rent": "house_rent",
           "commercial-sell": "commercial_sell", "commercial-rent": "commercial_rent"}

CAR_BRANDS = ["پژو", "سمند", "دنا", "رانا", "تارا", "هایما", "ریرا",
              "پراید", "تیبا", "ساینا", "کوییک", "شاهین", "اطلس",
              "تویوتا", "کیا", "هیوندای", "نیسان", "میتسوبیشی", "هوندا",
              "بنز", "بی ام و", "ب ام و", "آئودی", "فولکس", "رنو",
              "لیفان", "جک", "چری", "ام وی ام", "فوتون", "دیگنیتی",
              "فیدلیتی", "لاماری", "کلوت", "پیکاپ"]

MOTOR_BRANDS = ["یاماها", "هوندا", "کویر", "تی‌وی‌اس", "باجاج", "پالس",
                "سوزوکی", "کاوازاکی", "کی‌تی‌ام", "KTM", "آپاچی", "ان‌اس",
                "کلیک", "ویو", "ایروکس", "ان‌مکس", "پی‌سی‌ایکس", "هرو",
                "دیسکاور", "باکسر", "شکار", "تیزرو", "نامی"]

MOBILE_BRANDS = ["آیفون", "ایفون", "اپل", "سامسونگ", "سامسنگ", "شیائومی", "هواوی", "آنر", "نوکیا",
                 "موتورولا", "ریلمی", "پوکو", "وان‌پلاس", "گوگل", "پیکسل",
                 "ال‌جی", "سونی", "ایسوس", "تکنو", "اینفینیکس"]


def api_post(payload: dict, retries: int = 3) -> dict:
    import requests
    last = None
    for i in range(retries):
        try:
            r = requests.post(API, json=payload, timeout=30,
                              headers={"User-Agent": UA})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def parse_area_m2(title: str) -> float | None:
    m = re.search(r"([۰-۹0-9]+)\s*مت?ر", title)
    if m:
        return fa_digits_to_int(m.group(1))
    return None


def parse_car(title: str) -> tuple[str, str, int | None]:
    brand = ""
    for b in CAR_BRANDS:
        if b in title:
            brand = b
            break
    model = ""
    if brand:
        rest = title.split(brand, 1)[1].strip().split()
        model = " ".join(rest[:2])
    year = None
    m = re.search(r"(13\d\d|14\d\d|20\d\d)", title.replace("۰", "0").replace("۱", "1")
                  .replace("۲", "2").replace("۳", "3").replace("۴", "4").replace("۵", "5")
                  .replace("۶", "6").replace("۷", "7").replace("۸", "8").replace("۹", "9"))
    if m:
        year = int(m.group(1))
    return brand, model, year


def parse_brand(title: str, brands: list[str]) -> str:
    for b in brands:
        if b in title:
            return b
    return ""


def widget_to_ad(w: dict, category: str, city: str) -> Ad | None:
    d = w.get("data", {})
    payload = d.get("action", {}).get("payload", {})
    token = payload.get("token") or d.get("token")
    if not token:
        return None
    title = d.get("title", "")
    wi = payload.get("web_info", {})
    district = wi.get("district_persian", "")
    price = fa_digits_to_int(d.get("middle_description_text", ""))
    sort_date = (w.get("action_log", {}).get("server_side_info", {})
                 .get("info", {}).get("sort_date", ""))
    ad = Ad(token=token, title=title, category=CAT_MAP.get(category, category), city=city,
            district=district, price=price)
    engine_cat = ad.category
    if engine_cat in ("house_sell", "house_rent", "commercial_sell", "commercial_rent"):
        ad.area_m2 = parse_area_m2(title)
    elif engine_cat == "car":
        ad.brand, ad.model, ad.year = parse_car(title)
        km_txt = d.get("top_description_text", "")
        if "کیلومتر" in km_txt:
            ad.km = fa_digits_to_int(km_txt)
    elif engine_cat == "motorcycle":
        ad.brand = parse_brand(title, MOTOR_BRANDS)
        rest = title.split(ad.brand, 1)[1].strip().split() if ad.brand else []
        ad.model = " ".join(rest[:2])
        km_txt = d.get("top_description_text", "")
        if "کیلومتر" in km_txt:
            ad.km = fa_digits_to_int(km_txt)
    elif engine_cat == "mobile":
        ad.brand = parse_brand(title, MOBILE_BRANDS)
        if not ad.brand:
            ad.brand = _guess_mobile_brand(title)
    ad.sort_date = sort_date
    ad.img = d.get("image_url", "")
    return ad


def _guess_mobile_brand(title: str) -> str:
    """حدس برند از روی کلمات مدل وقتی اسم برند در تیتر نیست."""
    t = title.lower()
    if "گلکسی" in title or "galaxy" in t:
        return "سامسونگ"
    if "ردمی" in title or "redmi" in t or "پوکو" in title or "poco" in t:
        return "شیائومی"
    if re.search(r"(آیفون|iphone)", t):
        return "آیفون"
    # الگوی «۱۶ پرو / ۱۵ پرومکس / ۱۳ نرمال» بدون ذکر آیفون
    if re.search(r"\b(1[0-9]|x|se)\s*(pro\s*max|promax|pro|plus|mini|normal|نرمال)\b", t):
        return "آیفون"
    return ""


def init_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS ads(
        token TEXT PRIMARY KEY, title TEXT, category TEXT, city TEXT, district TEXT,
        price INTEGER, area_m2 REAL, brand TEXT, model TEXT, year INTEGER,
        img TEXT, km INTEGER, year_built INTEGER,
        sort_date TEXT, first_seen INTEGER, tier TEXT, discount REAL)""")
    # مایگریشن: ستون city برای دیتابیس‌های قدیمی
    cols = [r[1] for r in con.execute("PRAGMA table_info(ads)")]
    if "city" not in cols:
        con.execute("ALTER TABLE ads ADD COLUMN city TEXT DEFAULT 'تهران'")
        con.commit()
    con.execute("""CREATE TABLE IF NOT EXISTS baselines(
        city TEXT, district TEXT, category TEXT, segment TEXT, median INTEGER,
        n INTEGER, updated_at INTEGER,
        PRIMARY KEY (city, district, category, segment))""")
    con.execute("""CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, val TEXT)""")
    return con


def load_baseline(con: sqlite3.Connection) -> BaselineStore:
    b = BaselineStore()
    for city, district, cat, seg, median in con.execute(
            "SELECT city, district, category, segment, median FROM baselines"):
        b.set(city, district, cat, seg, int(median))
    return b


def rebuild_baselines(con: sqlite3.Connection) -> int:
    """میانهٔ قیمت از کل آگهی‌های دیده‌شده — هر ساعت یک‌بار صدا بزن."""
    from statistics import median
    from engine import _house_segment, _car_segment
    groups: dict[tuple, list[int]] = {}
    for token, title, category, city, district, price, area_m2, brand, model, year, year_built in con.execute(
            "SELECT token,title,category,city,district,price,area_m2,brand,model,year,year_built FROM ads WHERE price>0"):
        city = city or "تهران"
        if category in ("house_sell", "house_rent", "commercial_sell", "commercial_rent"):
            if not area_m2 or not district:
                continue
            ad = Ad(token=token, title=title, category=category, city=city, district=district,
                    price=price, area_m2=area_m2, year_built=year_built)
            seg = _house_segment(ad)
            key = (city, district, category, seg)
            groups.setdefault(key, []).append(price / area_m2)
        elif category == "mobile":
            if not brand:
                continue
            from engine import _mobile_segment
            ad = Ad(token=token, title=title, category=category, city=city, brand=brand or "")
            key = (city, "*", "mobile", _mobile_segment(ad))
            groups.setdefault(key, []).append(price)
        else:  # car, motorcycle
            if not brand:
                continue
            ad = Ad(token=token, title=title, category=category, city=city, brand=brand or "",
                    model=model or "", year=year)
            key = (city, "*", category, _car_segment(ad))
            groups.setdefault(key, []).append(price)
    now = int(time.time())
    n = 0
    for (city, district, cat, seg), prices in groups.items():
        if len(prices) < 3:
            continue
        con.execute("INSERT OR REPLACE INTO baselines VALUES (?,?,?,?,?,?,?)",
                    (city, district, cat, seg, int(median(prices)), len(prices), now))
        n += 1
    # فالبک شهر-واید: میانهٔ هر سگمنت در کل شهر (برای وقتی دیتای محله کم است)
    city_groups: dict[tuple, list[float]] = {}
    for (city, district, cat, seg), prices in groups.items():
        city_groups.setdefault((city, "*", cat, seg), []).extend(prices)
    for (city, district, cat, seg), prices in city_groups.items():
        if len(prices) < 5:
            continue
        con.execute("INSERT OR REPLACE INTO baselines VALUES (?,?,?,?,?,?,?)",
                    (city, district, cat, seg, int(median(prices)), len(prices), now))
        n += 1
    con.commit()
    return n


def fetch_newest(category: str, city_id: str) -> list[dict]:
    """فقط صفحهٔ اول (جدیدترین‌ها) هر شهر.
    توجه: صفحه‌های بعدی (pagination_data) از این خروجی پاسخ ناقص می‌دهند،
    پس عمداً فقط صفحهٔ اول گرفته می‌شود."""
    body: dict = {"city_ids": [city_id],
                  "search_data": {"form_data": {"data": {"category": {"str": {"value": category}}}}}}
    d = api_post(body)
    return d.get("list_widgets", [])


def poll_once(con: sqlite3.Connection, baseline: BaselineStore) -> list:
    """هر اجرا: همهٔ شهرها × هر دسته — فچ موازی با تردپول."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs = [(city_id, city_name, cat)
            for city_id, city_name in CITIES.items() for cat in CATEGORIES]

    def fetch_job(job):
        city_id, city_name, cat = job
        try:
            widgets = fetch_newest(cat, city_id)
            return (job, widgets, None)
        except Exception as e:
            return (job, [], f"{type(e).__name__}")

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(fetch_job, j): j for j in jobs}
        for fut in as_completed(futs):
            results.append(fut.result())

    fresh = []
    for (city_id, city_name, cat), widgets, err in results:
        if err:
            print(f"[{city_name}/{cat}] fetch failed: {err}")
            continue
        for w in widgets:
            ad = widget_to_ad(w, cat, city_name)
            if not ad:
                continue
            exists = con.execute("SELECT 1 FROM ads WHERE token=?", (ad.token,)).fetchone()
            if exists:
                continue
            s = score_ad(ad, baseline)
            tier = s.tier if s else "none"
            disc = round(s.discount_pct, 4) if s else 0.0
            con.execute("""INSERT INTO ads(token,title,category,city,district,price,area_m2,brand,model,year,img,km,year_built,sort_date,first_seen,tier,discount) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (ad.token, ad.title, ad.category, city_name, ad.district, ad.price,
                         ad.area_m2, ad.brand, ad.model, ad.year, ad.img, ad.km, ad.year_built,
                         getattr(ad, "sort_date", ""), int(time.time()), tier, disc))
            if tier != "none":
                fresh.append((ad, s))
    con.commit()
    print(f"poll: {len(jobs)} city×cat fetched, {len(fresh)} fresh deals")
    return fresh


def main():
    con = init_db()
    # بوت‌استرپ اولیه: اگر دیتابیس خالی است، ۳ صفحه بگیر و بیس‌لاین بساز
    n_ads = con.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
    if n_ads == 0:
        print("bootstrap: fetching first pages (parallel)...")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        jobs = [(cid, cname, cat) for cid, cname in CITIES.items() for cat in CATEGORIES]
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(fetch_newest, cat, cid): (cname, cat) for cid, cname, cat in jobs}
            for fut in as_completed(futs):
                cname, cat = futs[fut]
                try:
                    widgets = fut.result()
                except Exception as e:
                    print(f"[{cname}/{cat}] bootstrap fetch failed: {type(e).__name__}; skipping")
                    continue
                for w in widgets:
                    ad = widget_to_ad(w, cat, cname)
                    if ad and not con.execute("SELECT 1 FROM ads WHERE token=?", (ad.token,)).fetchone():
                        con.execute("""INSERT INTO ads(token,title,category,city,district,price,area_m2,brand,model,year,img,km,year_built,sort_date,first_seen,tier,discount) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                    (ad.token, ad.title, ad.category, cname, ad.district, ad.price,
                                     ad.area_m2, ad.brand, ad.model, ad.year, ad.img, ad.km, ad.year_built,
                                     getattr(ad, "sort_date", ""), int(time.time()), "none", 0.0))
                con.commit()
        nb = rebuild_baselines(con)
        print(f"bootstrap done: baselines={nb}")
    baseline = load_baseline(con)
    # بازامتیازدهی آگهی‌های قبلی با بیس‌لاین تازه (برای بوت‌استرپ و کالیبراسیون)
    rescored = 0
    for row in con.execute(
            "SELECT token,title,category,city,district,price,area_m2,brand,model,year FROM ads WHERE tier='none'"):
        token, title, category, city, district, price, area_m2, brand, model, year = row
        ad = Ad(token=token, title=title, category=category, city=city or "تهران", district=district,
                price=price, area_m2=area_m2, brand=brand or "", model=model or "", year=year)
        s = score_ad(ad, baseline)
        if s and s.tier != "none":
            con.execute("UPDATE ads SET tier=?, discount=? WHERE token=?",
                        (s.tier, round(s.discount_pct, 4), token))
            rescored += 1
    if rescored:
        con.commit()
        print(f"rescored: {rescored} new deals from existing ads")
    fresh = poll_once(con, baseline)
    for ad, s in fresh:
        print(f"[{TIER_FA[s.tier]} {s.discount_pct:.0%}] {ad.title[:50]} — {ad.district} — {ad.price:,}")
    # کالیبراسیون ساعتی بیس‌لاین
    last = con.execute("SELECT val FROM meta WHERE key='last_rebase'").fetchone()
    if not last or time.time() - int(last[0]) > 3600:
        nb = rebuild_baselines(con)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('last_rebase',?)", (str(int(time.time())),))
        con.commit()
        print(f"rebaselined: {nb} segments")
    con.close()


if __name__ == "__main__":
    main()

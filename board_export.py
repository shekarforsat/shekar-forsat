#!/usr/bin/env python3
"""board_export.py — static-site generator for Shekar Forsat (قاپ) v4.

Dallal-style redesign (Mohsen's order, 2026-10-09): newspaper aesthetic —
cream paper, petrol ink, lime highlighter accents, giant headlines, rule
lines, flat cards. Persian RTL, dark "newspaper night" mode, live ticker,
count-up hero numbers, rotating feature card, quick city/category filters,
search, and a localStorage-backed "my list" drawer.

Architecture (unchanged from v3): reads the `ads` table from SQLite,
writes index.html + city/<slug>.html + cat/<slug>.html + deals.json
(a dict with a deals list), sitemap.xml and robots.txt.
CLI: --db/--out/--limit.
"""
import argparse
import json, os, sqlite3
from datetime import datetime, timezone, timedelta

DB_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deals.db")
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")

TEHRAN = timezone(timedelta(hours=3, minutes=30))

CITY_SLUG = {
    "آذربایجان شرقی": "tabriz", "آذربایجان غربی": "urmia", "اردبیل": "ardabil",
    "اصفهان": "isfahan", "البرز": "karaj", "ایلام": "ilam", "بوشهر": "bushehr",
    "تهران": "tehran", "چهارمحال و بختیاری": "shahrekord", "خراسان جنوبی": "birjand",
    "خراسان رضوی": "mashhad", "خراسان شمالی": "bojnurd", "خوزستان": "ahvaz",
    "زنجان": "zanjan", "سمنان": "semnan", "سیستان و بلوچستان": "zahedan",
    "فارس": "shiraz", "قزوین": "qazvin", "قم": "qom", "کردستان": "sanandaj",
    "کرمان": "kerman", "کرمانشاه": "kermanshah", "کهگیلویه و بویراحمد": "yasuj",
    "گلستان": "gorgan", "گیلان": "rasht", "لرستان": "khorramabad",
    "مازندران": "sari", "مرکزی": "arak", "هرمزگان": "bandar-abbas",
    "همدان": "hamedan", "یزد": "yazd",
}

CATS = {
    "house_sell": ("foroush-maskan", "فروش مسکن", "آپارتمان و خانه زیر قیمت"),
    "house_rent": ("ejareh-maskan", "اجاره مسکن", "آپارتمان اجاره زیر قیمت"),
    "car": ("khodro", "خودرو", "ماشین زیر قیمت"),
    "motorcycle": ("motorcyclet", "موتورسیکلت", "موتور زیر قیمت"),
    "mobile": ("mobile", "موبایل", "گوشی موبایل زیر قیمت"),
    "commercial_sell": ("melk-tejari", "ملک تجاری", "مغازه و ملک تجاری زیر قیمت"),
    "commercial_rent": ("ejareh-tejari", "اجاره تجاری", "اجاره مغازه زیر قیمت"),
}
CAT_FA = {c: v[1] for c, v in CATS.items()}

CAT_ICON = {"house_sell": "home", "house_rent": "home", "commercial_sell": "home",
            "commercial_rent": "home", "car": "car", "motorcycle": "car", "mobile": "digital"}

# Stroke-icon inner paths (viewBox 0 0 96 96) in the dallal sample's hand-drawn style.
ICON_PATHS = {
    "home": ('<path d="M16 44 48 18l32 26v34H58V57H38v21H16V44Z"/>'
              '<path d="M64 24V13h10v19"/>'),
    "car": ('<path d="M17 55h62l-7-22H31L17 55Z"/>'
             '<path d="M11 55v16h8m60-16v16h-8M27 71h44"/>'
             '<circle cx="28" cy="70" r="7"/><circle cx="65" cy="70" r="7"/>'),
    "digital": ('<rect x="21" y="16" width="55" height="45" rx="3"/>'
                 '<path d="M12 69h73l-5 9H17l-5-9Z"/>'),
}
ICON_SVG = {
    k: ('<svg viewBox="0 0 96 96" fill="none" stroke="currentColor" stroke-width="3" '
        'stroke-linejoin="round" aria-hidden="true">' + v + '</svg>')
    for k, v in ICON_PATHS.items()
}

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(n):
    s = f"{n:,}" if isinstance(n, int) else str(n)
    return s.translate(FA_DIGITS)


def load_deals(db_path, limit=80, city=None, category=None):
    con = sqlite3.connect(db_path)
    q = """SELECT token,title,category,city,district,price,tier,discount,first_seen
           FROM ads WHERE tier IN ('golden','opportunity') AND price>0"""
    params = []
    if city:
        q += " AND city=?"; params.append(city)
    if category:
        if category == "car":
            q += " AND category IN ('car','cars')"
        else:
            q += " AND category=?"; params.append(category)
    q += """ ORDER BY CASE tier WHEN 'golden' THEN 0 ELSE 1 END, discount DESC, first_seen DESC
             LIMIT ?"""
    params.append(limit)
    rows = con.execute(q, params).fetchall()
    counts = {(c, k): n for c, k, n in
              con.execute("SELECT city, category, COUNT(*) FROM ads GROUP BY city, category").fetchall()}
    con.close()
    deals = []
    for token, title, category, city, district, price, tier, discount, _ in rows:
        discount = discount or 0.0
        fair = round(price / (1 - discount)) if discount > 0 else price
        cat = "car" if category == "cars" else (category or "")
        deals.append({
            "divar_token": token, "title": title or "", "category": cat,
            "cat_fa": CAT_FA.get(cat, cat), "city": city or "", "district": district or "",
            "price": price, "fair_price": fair, "pct_below_fair": round(discount, 4),
            "tier": tier, "n_comps": counts.get((city, category), 0),
            "icon": CAT_ICON.get(cat, "home"),
            "url": "https://divar.ir/v/" + token,
        })
    return deals


# --- تبدیل گریگوری به جلالی (الگوریتم چرخه‌ای استاندارد) ---
def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
            + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1])
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


JMONTHS = ["", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
           "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def tehran_now_fa():
    now = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{fa_num(jd)} {JMONTHS[jm]} {fa_num(jy)} — ساعت {fa_num(f'{now.hour:02d}:{now.minute:02d}')}"


def _conf(n):
    if n is None:
        return "نامشخص"
    return "بالا" if n >= 50 else ("خوب" if n >= 15 else "پایه")


def city_slug(name):
    key = (name or "").replace("‌", "").replace(" ", "")
    for k, v in CITY_SLUG.items():
        if k.replace("‌", "") == key:
            return v
    return "other"


SITE_URL = os.environ.get("SITE_URL", "https://shekarforsat.github.io/shekar-forsat").rstrip("/")

DISCLAIMER = ("درصدهای «زیر قیمت» برآورد ما از قیمت منصفانهٔ هر محله/مدل‌اند و ممکن است "
              "با واقعیت بازار اختلاف داشته باشند؛ قبل از هر تصمیمی، خودتان آگهی و محله را بررسی کنید.")


STYLE = """
    :root{
      color-scheme:light dark;
      --paper:#f6f4e9;--ink:#082f33;--muted:#52696a;--accent:#d9f24b;--line:#103f42;
      --soft:#e7e8db;--card:#fbfaf2;--quiet:#d7ddd4;--danger:#8f3c31;
      --max:1180px;
    }
    @media(prefers-color-scheme:dark){:root{--paper:#0a2426;--ink:#edf1df;--muted:#b3c1b9;--accent:#d7ef48;--line:#d5dfd3;--soft:#173437;--card:#102d30;--quiet:#385052;--danger:#ff9f8d}}
    html[data-theme="light"]{--paper:#f6f4e9;--ink:#082f33;--muted:#52696a;--accent:#d9f24b;--line:#103f42;--soft:#e7e8db;--card:#fbfaf2;--quiet:#d7ddd4;--danger:#8f3c31;color-scheme:light}
    html[data-theme="dark"]{--paper:#0a2426;--ink:#edf1df;--muted:#b3c1b9;--accent:#d7ef48;--line:#d5dfd3;--soft:#173437;--card:#102d30;--quiet:#385052;--danger:#ff9f8d;color-scheme:dark}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Vazirmatn",Tahoma,sans-serif;line-height:1.7;overflow-x:hidden}body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:20;opacity:.055;background-image:repeating-radial-gradient(circle at 17% 31%,var(--ink) 0 .45px,transparent .7px 4px),repeating-radial-gradient(circle at 73% 68%,var(--ink) 0 .35px,transparent .65px 5px);background-size:7px 9px,11px 13px;mix-blend-mode:multiply}
    @media(prefers-color-scheme:dark){body::before{opacity:.035;mix-blend-mode:screen}}
    button,a{font:inherit}a{color:inherit}.wrap{width:min(var(--max),calc(100% - 36px));margin:auto}
    .mast{border-bottom:3px solid var(--line);padding:12px 0 10px}.mast-inner{display:flex;align-items:center;justify-content:space-between;gap:24px}.brand{font-weight:900;font-size:27px;letter-spacing:-1.5px;line-height:1.18;position:relative;padding-inline:2px;text-decoration:none}.brand::after{content:"";position:absolute;right:-3px;left:-3px;bottom:-2px;height:8px;background:var(--accent);z-index:-1;transform:rotate(-1deg)}
    .nav{display:flex;gap:24px;align-items:center;font-size:14px;font-weight:700}.nav a{text-decoration:none}.nav a:hover,.nav a:focus-visible{text-decoration:underline;text-underline-offset:5px}.mast-tools{display:flex;align-items:center;gap:10px}.live-badge{font-size:12px;border:1px solid var(--line);padding:4px 10px;border-radius:999px;white-space:nowrap;display:inline-flex;align-items:center;gap:6px;font-weight:800}.live-badge i{width:7px;height:7px;border-radius:50%;background:var(--accent);border:1px solid var(--ink);animation:pulse 2.2s infinite}.icon-button{border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:999px;padding:6px 11px;cursor:pointer;font-weight:800;white-space:nowrap}.icon-button:hover,.icon-button:focus-visible{background:var(--accent);color:#082f33}.edition{border-bottom:1px solid var(--line);font-size:11px;font-weight:700;padding:7px 0}.edition .wrap{display:flex;justify-content:space-between;gap:16px;align-items:center}.edition-label{color:var(--muted)}
    .ticker-shell{overflow:hidden;background:var(--accent);color:#082f33;border-bottom:2px solid var(--line)}.ticker-track{display:flex;align-items:center;width:max-content;white-space:nowrap;animation:tickerMove 28s linear infinite}.ticker-run{display:flex;gap:18px;align-items:center;padding:9px 9px 8px;font-size:12px;font-weight:650}.ticker-run b{font-weight:900}.ticker-shell .dot{width:5px;height:5px;border-radius:50%;background:#082f33;flex:0 0 auto}@keyframes tickerMove{from{transform:translateX(0)}to{transform:translateX(50%)}}
    .hero{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(260px,.55fr);gap:62px;padding:70px 0 58px;align-items:end}.kicker{font-size:12px;font-weight:800;margin:0 0 12px}.hero h1{font-size:clamp(40px,6.7vw,82px);line-height:1.08;letter-spacing:-3.6px;margin:0;max-width:930px;font-weight:900}.mark{position:relative;display:inline-block;z-index:0}.mark::after{content:"";position:absolute;right:-4px;left:-4px;height:.31em;bottom:.09em;background:var(--accent);z-index:-1;transform:rotate(-1deg)}.outline-number{display:inline-block;color:var(--paper);-webkit-text-stroke:1.45px var(--ink);paint-order:stroke fill;text-shadow:2px 2px 0 color-mix(in srgb,var(--accent) 76%,transparent);font-variant-numeric:tabular-nums}.hero-aside .outline-number{font-size:56px;line-height:1;font-weight:900;-webkit-text-stroke:1.2px var(--ink)}
    .lede{font-size:18px;max-width:680px;margin:26px 0 29px;color:var(--muted)}.actions{display:flex;align-items:center;gap:20px;flex-wrap:wrap}.primary{display:inline-flex;align-items:center;gap:13px;border:0;background:var(--ink);color:var(--paper);border-radius:999px;padding:13px 22px;text-decoration:none;font-weight:800;cursor:pointer}.primary:hover{filter:contrast(1.08)}.text-link{text-underline-offset:5px;font-weight:700}.hero-aside{border-top:3px solid var(--line);padding-top:16px}.hero-aside p{margin:8px 0 0;color:var(--muted);font-size:14px}.pulse{width:10px;height:10px;display:inline-block;border-radius:50%;background:var(--accent);border:1px solid var(--ink);margin-left:6px;animation:pulse 2.2s infinite}@keyframes pulse{50%{box-shadow:0 0 0 7px color-mix(in srgb,var(--accent) 20%,transparent)}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}.pulse,.ticker-track,.card,.feature-progress span{animation:none!important}.cards.is-staggering .card{opacity:1!important;transform:none!important}}
    .section{border-top:3px solid var(--line);padding:24px 0 68px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:28px}.section h2{font-size:clamp(28px,4vw,46px);line-height:1.25;margin:0;letter-spacing:-1.4px}.section-note{max-width:460px;margin:0;color:var(--muted);font-size:14px}.feature{display:grid;grid-template-columns:.8fr 1.2fr;border:7px double var(--accent);outline:1px solid var(--line);background:var(--card);border-radius:18px;overflow:hidden;margin:4px;box-shadow:8px 8px 0 var(--soft)}.visual{min-height:360px;position:relative;overflow:hidden;background:var(--soft);border-left:1px solid var(--line);display:grid;place-items:center}.visual svg{width:76%;height:auto}.visual .stamp{position:absolute;top:24px;left:24px;border:2px solid var(--ink);border-radius:50%;width:100px;height:100px;display:grid;place-items:center;text-align:center;font-weight:900;transform:rotate(-8deg);background:var(--accent);line-height:1.25}.feature-copy{padding:clamp(24px,5vw,58px)}.meta{display:flex;gap:10px;flex-wrap:wrap;font-size:13px;font-weight:700}.meta span{border-left:1px solid var(--quiet);padding-left:10px}.meta span:last-child{border:0}.feature h3{font-size:clamp(30px,4.5vw,56px);line-height:1.12;margin:18px 0 12px;letter-spacing:-2px}.price{font-size:24px;font-weight:900;margin-bottom:25px}.meter{margin:20px 0}.meter-labels{display:flex;justify-content:space-between;font-size:12px;font-weight:700;margin-bottom:7px}.meter-track{height:14px;border:1px solid var(--ink);position:relative;background:var(--quiet)}.meter-fill{height:100%;background:var(--accent);border-left:1px solid var(--ink)}.deal-bar{margin:14px 0 4px}.deal-bar-head{display:flex;justify-content:space-between;gap:12px;font-size:11px;font-weight:800}.deal-bar-track{height:6px;background:var(--quiet);margin-top:6px;overflow:hidden}.deal-bar-fill{height:100%;background:var(--accent);border-left:1px solid var(--ink)}.confidence{font-size:13px;border-top:1px solid var(--quiet);padding-top:15px;margin-top:20px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.card{border:1px solid var(--line);border-radius:15px;background:var(--card);padding:22px;display:flex;flex-direction:column;min-width:0;position:relative}.card-main{display:flex;flex-direction:column;flex:1;text-decoration:none;color:inherit;min-width:0}.bookmark{position:absolute;top:18px;left:18px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;width:39px;height:39px;display:grid;place-items:center;cursor:pointer;font-size:19px;font-weight:900;z-index:2}.bookmark[aria-pressed="true"]{background:var(--accent);color:#082f33}.cards.is-staggering .card{opacity:0;animation:cardIn .48s cubic-bezier(.22,.8,.3,1) forwards;animation-delay:var(--delay,0ms)}@keyframes cardIn{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:translateY(0)}}.card-icon{height:142px;background:var(--soft);border-radius:8px;margin:-10px -10px 18px;display:grid;place-items:center}.card-icon svg{width:92px;height:92px}.card h3{font-size:25px;line-height:1.3;margin:12px 0 6px}.deal-title{font-size:16px;font-weight:800;margin:0 0 12px;line-height:1.6}.card .price{font-size:18px;margin:0 0 15px}.card .text-link{margin-top:auto;padding-top:16px}.discovery-tools{display:grid;grid-template-columns:minmax(230px,1fr) auto;gap:16px;align-items:end;margin:0 0 22px}.search-label{display:grid;gap:6px;font-size:12px;font-weight:800}.search{width:100%;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:0;padding:12px 14px;outline:none}.search:focus{box-shadow:inset 0 -4px 0 var(--accent)}.filter-bar{display:flex;align-items:center;justify-content:space-between;gap:16px}.tabs{display:flex;gap:8px;flex-wrap:wrap}.tab{border:1px solid var(--line);color:var(--ink);background:transparent;border-radius:999px;padding:7px 16px;cursor:pointer;font-weight:700;transition:background .18s,color .18s,box-shadow .18s}.tab:hover{box-shadow:inset 0 -3px 0 var(--accent)}.tab[aria-pressed="true"]{background:var(--ink);color:var(--paper);box-shadow:inset 0 -4px 0 var(--accent)}.filter-status{font-size:12px;color:var(--muted);white-space:nowrap}.feature-nav{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:17px}.feature-dots{display:flex;gap:8px}.feature-dot{width:12px;height:12px;border:1px solid var(--line);background:transparent;border-radius:50%;padding:0;cursor:pointer}.feature-dot[aria-pressed="true"]{background:var(--accent);box-shadow:inset 0 0 0 2px var(--card)}.feature-progress{height:2px;background:var(--quiet);flex:1;overflow:hidden}.feature-progress span{display:block;height:100%;background:var(--ink);transform-origin:right;animation:featureProgress 7s linear}@keyframes featureProgress{from{transform:scaleX(0)}to{transform:scaleX(1)}}
    .method{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-right:1px solid var(--line)}.step{padding:28px;border-left:1px solid var(--line);border-bottom:1px solid var(--line);min-height:220px}.num{font-weight:900;font-size:15px;background:var(--accent);border-radius:50%;width:34px;height:34px;display:grid;place-items:center;margin-bottom:35px;color:#082f33}.step h3{font-size:20px;margin:0 0 8px}.step p{margin:0;color:var(--muted);font-size:14px}
    .faq{max-width:900px}.faq details{border-top:1px solid var(--line);padding:0}.faq details:last-child{border-bottom:1px solid var(--line)}.faq summary{list-style:none;cursor:pointer;padding:19px 0;font-size:18px;font-weight:800;display:flex;justify-content:space-between;gap:20px}.faq summary::-webkit-details-marker{display:none}.faq summary::after{content:"＋"}.faq details[open] summary::after{content:"−"}.faq p{margin:0 0 22px;color:var(--muted);max-width:760px}.drawer-backdrop{position:fixed;inset:0;background:rgba(4,25,27,.48);z-index:40;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .2s,visibility 0s linear .2s}.drawer-backdrop.is-open{opacity:1;visibility:visible;pointer-events:auto;transition-delay:0s}.drawer{position:absolute;left:0;top:0;bottom:0;width:min(420px,92vw);background:var(--paper);color:var(--ink);border-right:3px solid var(--line);padding:22px;transform:translateX(-100%);transition:transform .24s;overflow:auto}.drawer-backdrop.is-open .drawer{transform:translateX(0)}.drawer-head{display:flex;justify-content:space-between;align-items:center;gap:15px;border-bottom:3px solid var(--line);padding-bottom:14px}.drawer h2{font-size:27px;margin:0}.drawer-list{display:grid;gap:12px;margin-top:18px}.saved-item{border-bottom:1px solid var(--line);padding:0 0 14px}.saved-item h3{font-size:17px;margin:0 0 3px}.saved-item p{font-size:12px;color:var(--muted);margin:0}.empty{color:var(--muted);font-size:14px}.session-note{font-size:11px;color:var(--muted);margin-top:20px}
    footer{border-top:3px solid var(--line);padding:28px 0 42px}.foot{display:grid;grid-template-columns:1fr 2fr;gap:40px}.foot strong{font-size:26px}.fine{font-size:12px;color:var(--muted);margin:0}
    .promo{width:min(var(--max),calc(100% - 36px));margin:0 auto 68px}.promo-box{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap;padding:clamp(22px,3vw,34px) clamp(24px,4vw,44px);border:1px solid var(--line);border-radius:18px;background:var(--ink);color:var(--paper);box-shadow:8px 8px 0 var(--soft)}.promo-box strong{font-size:20px;font-weight:900}.promo-box strong .mark::after{height:.3em}.promo-box p{margin:6px 0 0;color:var(--muted);font-size:14px}.promo-box a{min-height:48px;display:inline-flex;align-items:center;padding:0 26px;border-radius:999px;background:var(--accent);color:#082f33;font-weight:900;text-decoration:none;font-size:15px}
    .chips{display:flex;gap:8px;flex-wrap:wrap;padding:14px 0}.chip{border:1px solid var(--line);color:var(--ink);background:transparent;border-radius:999px;padding:7px 16px;cursor:pointer;font-weight:700;text-decoration:none;font-size:13px}.chip:hover{box-shadow:inset 0 -3px 0 var(--accent)}.chip.on{background:var(--ink);color:var(--paper);box-shadow:inset 0 -4px 0 var(--accent)}.page-head{padding:38px 0 8px}.page-head h1{font-size:clamp(30px,4.5vw,52px);letter-spacing:-2px;margin:0 0 10px;font-weight:900}.page-head .intro{color:var(--muted);max-width:62ch}
    .empty-box{padding:60px 20px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:18px;background:var(--card)}
    @media(max-width:820px){.nav{display:none}.hero{grid-template-columns:1fr;gap:30px;padding:46px 0}.hero h1{letter-spacing:-2px}.hero-aside{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:15px}.feature{grid-template-columns:1fr}.visual{min-height:260px;border:0;border-bottom:1px solid var(--line)}.cards,.method{grid-template-columns:1fr}.step{min-height:0}.section-head{display:block}.section-note{margin-top:12px}.discovery-tools{grid-template-columns:1fr}.filter-bar{align-items:flex-start;flex-direction:column}.foot{grid-template-columns:1fr}.section{padding-bottom:48px}.edition .wrap{align-items:flex-start;flex-direction:column;gap:1px}}
    @media(max-width:480px){.wrap{width:min(100% - 24px,var(--max))}.hero h1{font-size:39px}.lede{font-size:16px}.feature{margin:4px 2px;box-shadow:5px 5px 0 var(--soft)}.feature-copy{padding:23px}.visual .stamp{width:78px;height:78px;font-size:13px;top:16px;left:16px}.ticker-run{font-size:11px}.tab{padding:6px 12px}.live-badge{display:none}.brand{font-size:24px}.mast-tools{gap:6px}.icon-button{font-size:11px;padding:6px 9px}.deal-bar-head{font-size:10px}}
"""


# ---------- shared JS: theme + saved list (localStorage) + drawer ----------
SHARED_JS = """
(function(){
  window.faNum = function(n){ return String(n).replace(/\\d/g, function(x){ return '۰۱۲۳۴۵۶۷۸۹'[x]; }); };
  window.faPrice = function(n){ return faNum(Number(n).toLocaleString('en-US')); };
  window.dealDiscount = function(d){ return Math.round(d.pct_below_fair * 100); };
  window.dealConf = function(n){ return n == null ? 'نامشخص' : n >= 50 ? 'بالا' : n >= 15 ? 'خوب' : 'پایه'; };
  window.dealById = function(id){ var ds = window.PAGE_DEALS || []; for (var i = 0; i < ds.length; i++){ if (ds[i].divar_token === id) return ds[i]; } return null; };

  var SAVED_KEY = 'qap-saved-v1';
  function loadSaved(){ try { var a = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]'); return new Set(a.filter(function(x){ return typeof x === 'string'; })); } catch(e){ return new Set(); } }
  window.savedDeals = loadSaved();
  function persistSaved(){ try { localStorage.setItem(SAVED_KEY, JSON.stringify(Array.from(window.savedDeals))); } catch(e){} }
  window.toggleSaved = function(id){
    if (window.savedDeals.has(id)) window.savedDeals.delete(id); else window.savedDeals.add(id);
    persistSaved(); syncBookmarks(); renderSaved();
  };
  window.bookmarkHTML = function(d){
    var active = window.savedDeals.has(d.divar_token);
    return '<button class="bookmark" type="button" data-save="' + d.divar_token + '" aria-pressed="' + active + '" aria-label="' + (active ? 'حذف از لیست من' : 'افزودن به لیست من') + '">' + (active ? '✓' : '＋') + '</button>';
  };
  function syncBookmarks(){
    document.querySelectorAll('[data-save]').forEach(function(b){
      var id = b.getAttribute('data-save'), active = window.savedDeals.has(id);
      b.setAttribute('aria-pressed', active); b.textContent = active ? '✓' : '＋';
      b.setAttribute('aria-label', active ? 'حذف از لیست من' : 'افزودن به لیست من');
    });
  }
  document.addEventListener('click', function(e){
    var b = e.target.closest('[data-save]');
    if (b) window.toggleSaved(b.getAttribute('data-save'));
  });
  function renderSaved(){
    var list = document.getElementById('savedList'); if (!list) return;
    var items = Array.from(window.savedDeals).map(window.dealById).filter(Boolean);
    var cnt = document.getElementById('savedCount'); if (cnt) cnt.textContent = faNum(items.length);
    list.innerHTML = items.length ? items.map(function(d){
      return '<article class="saved-item"><h3>' + d.title + '</h3><p>' + faNum(dealDiscount(d)) + '٪ زیر قیمت همتا · ' + d.city + ' · ' + d.cat_fa + '</p></article>';
    }).join('') : '<p class="empty">هنوز فرصتی نشان نکرده‌ای.</p>';
  }
  window.renderSaved = renderSaved;
  var drawer = document.getElementById('savedDrawer'), savedClose = document.getElementById('savedClose');
  function setDrawer(open){ if (!drawer) return; drawer.hidden = !open; drawer.classList.toggle('is-open', open); document.body.style.overflow = open ? 'hidden' : ''; if (open && savedClose) savedClose.focus(); }
  var savedToggle = document.getElementById('savedToggle');
  if (savedToggle) savedToggle.addEventListener('click', function(){ setDrawer(true); });
  if (savedClose) savedClose.addEventListener('click', function(){ setDrawer(false); });
  if (drawer) drawer.addEventListener('click', function(e){ if (e.target === drawer) setDrawer(false); });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape') setDrawer(false); });

  var themeToggle = document.getElementById('themeToggle');
  function currentDark(){ var x = document.documentElement.getAttribute('data-theme'); return x ? x === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches; }
  function syncThemeButton(){ if (!themeToggle) return; var dark = currentDark(); themeToggle.textContent = dark ? 'حالت روز' : 'حالت شب'; themeToggle.setAttribute('aria-pressed', dark); }
  if (themeToggle) themeToggle.addEventListener('click', function(){ document.documentElement.setAttribute('data-theme', currentDark() ? 'light' : 'dark'); syncThemeButton(); });
  syncThemeButton();

  var now = new Date();
  var dateText = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { timeZone: 'Asia/Tehran', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(now);
  var ed = document.getElementById('editionDate'); if (ed) ed.textContent = 'دفتر روزانه · ' + dateText;
  var parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tehran', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  var dp = {}; parts.forEach(function(p){ dp[p.type] = p.value; });
  var dayStart = Date.UTC(Number(dp.year), 0, 1), today = Date.UTC(Number(dp.year), Number(dp.month) - 1, Number(dp.day));
  var dayNumber = Math.floor((today - dayStart) / 86400000) + 1;
  var en = document.getElementById('editionNumber'); if (en) en.textContent = 'شمارهٔ روز ' + faNum(dayNumber);
  renderSaved();
})();
"""


def meter_html(d):
    pct = max(0, min(100, round(d["price"] / d["fair_price"] * 100))) if d["fair_price"] else 100
    return (
        '<div class="meter" aria-label="قیمت آگهی ' + fa_num(pct) + ' درصد قیمت همتا است">'
        '<div class="meter-labels"><span>آگهی: ' + fa_num(f"{d['price']:,}") + ' تومان</span>'
        '<span>همتا: ' + fa_num(f"{d['fair_price']:,}") + ' تومان</span></div>'
        '<div class="meter-track"><div class="meter-fill" style="width:' + str(pct) + '%"></div></div></div>'
    )


def deal_bar_html(d):
    pct = round(d["pct_below_fair"] * 100)
    return (
        '<div class="deal-bar" aria-label="فاصله از قیمت همتا ' + fa_num(pct) + ' درصد">'
        '<div class="deal-bar-head"><span>فاصله از همتا</span><strong>' + fa_num(pct) + '٪ زیر بازار</strong></div>'
        '<div class="deal-bar-track"><div class="deal-bar-fill" style="width:' + str(min(100, pct * 3)) + '%"></div></div></div>'
    )


def card_static_html(d, delay_ms=0):
    """Server-rendered deal card (city/cat pages) — mirrors the client renderer."""
    pct = round(d["pct_below_fair"] * 100)
    icon = ICON_SVG.get(d.get("icon", "home"), ICON_SVG["home"])
    loc = d["district"] or d["city"]
    return (
        '<article class="card" style="--delay:' + str(delay_ms) + 'ms">'
        + bookmark_static_html(d) +
        '<div class="card-main">'
        '<div class="card-icon">' + icon + '</div>'
        '<div class="meta"><span>' + d["cat_fa"] + '</span><span>' + loc + '</span></div>'
        '<h3><span class="mark">' + fa_num(pct) + '٪</span> زیر قیمت همتا</h3>'
        '<div class="deal-title">' + d["title"] + '</div>'
        + meter_html(d) + deal_bar_html(d) +
        '<div class="confidence">' + fa_num(d["n_comps"]) + ' نمونهٔ همتا · اطمینان ' + _conf(d["n_comps"]) + '</div>'
        '</div></article>'
    )


def bookmark_static_html(d):
    # aria-pressed is synced client-side from localStorage; default unpressed.
    return ('<button class="bookmark" type="button" data-save="' + d["divar_token"] +
            '" aria-pressed="false" aria-label="افزودن به لیست من">＋</button>')


def masthead_html(prefix="", index_mode=True):
    if index_mode:
        nav = ('<nav class="nav" aria-label="ناوبری"><a href="#opportunities">فرصت‌ها</a>'
               '<a href="#method">روش قاپ</a><a href="#questions">پرسش‌ها</a></nav>')
        brand_href = prefix + "index.html"
    else:
        nav = ('<nav class="nav" aria-label="ناوبری"><a href="' + prefix + 'index.html#opportunities">فرصت‌ها</a>'
               '<a href="' + prefix + 'index.html#method">روش قاپ</a>'
               '<a href="' + prefix + 'index.html#questions">پرسش‌ها</a></nav>')
        brand_href = prefix + "index.html"
    return (
        '<header class="mast"><div class="wrap mast-inner">'
        '<a class="brand" href="' + brand_href + '" aria-label="قاپ">قاپ</a>' + nav +
        '<div class="mast-tools">'
        '<span class="live-badge"><i></i>برد زنده</span>'
        '<button class="icon-button" id="themeToggle" type="button" aria-pressed="false">حالت شب</button>'
        '<button class="icon-button" id="savedToggle" type="button" aria-haspopup="dialog">لیست من · '
        '<span id="savedCount">۰</span></button>'
        '</div></div></header>'
    )


def edition_html(updated_fa):
    return (
        '<div class="edition"><div class="wrap"><span id="editionDate">دفتر روزانه</span>'
        '<span class="edition-label"><span id="editionNumber">شمارهٔ روز</span> · به‌روزرسانی: '
        + updated_fa + '</span></div></div>'
    )


def chips_html(cities, cats, prefix="", active_city=None, active_cat=None):
    home = '<a class="chip%s" href="%sindex.html">همه</a>' % (
        " on" if not (active_city or active_cat) else "", prefix)
    city_chips = "".join(
        '<a class="chip%s" href="%scity/%s.html">%s</a>' % (
            " on" if active_city == c else "", prefix, city_slug(c), c)
        for c in cities)
    cat_chips = "".join(
        '<a class="chip%s" href="%scat/%s.html">%s</a>' % (
            " on" if active_cat == k else "", prefix, CATS[k][0], CATS[k][1])
        for k in cats)
    return '<div class="wrap"><div class="chips">' + home + cat_chips + city_chips + "</div></div>"


FOOT_HTML = (
    '<footer><div class="wrap foot"><strong>فرصت را زودتر ببین.</strong>'
    '<p class="fine">DISCLAIMER_TXT<br><span id="updated"></span></p></div></footer>'
    '<div class="drawer-backdrop" id="savedDrawer" role="dialog" hidden aria-modal="true" aria-labelledby="savedTitle">'
    '<aside class="drawer"><div class="drawer-head"><h2 id="savedTitle">لیست من</h2>'
    '<button class="icon-button" id="savedClose" type="button">بستن</button></div>'
    '<div class="drawer-list" id="savedList"></div>'
    '<p class="session-note">انتخاب‌ها در همین مرورگر ذخیره می‌شوند.</p></aside></div>'
).replace("DISCLAIMER_TXT", DISCLAIMER)


INDEX_HTML = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<meta name="color-scheme" content="light dark"/>
<meta name="theme-color" content="#f6f4e9" media="(prefers-color-scheme: light)"/>
<meta name="theme-color" content="#0a2426" media="(prefers-color-scheme: dark)"/>
<link rel="icon" href="data:,"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800;900&display=swap" rel="stylesheet"/>
<title>قاپ | شکار فرصت‌های زیرقیمت</title>
<meta name="description" content="قاپ آگهی‌های دیوار را با قیمت منصفانه بازار مقایسه می‌کند و فرصت‌های واقعی زیرقیمت را نشان می‌دهد."/>
<style>{STYLE}</style>
</head>
<body>
{MASTHEAD}
{EDITION}
<div class="ticker-shell" aria-label="تازه‌ترین فرصت‌ها"><div class="ticker-track" id="tickerTrack"></div></div>
<main>
  <section class="wrap hero">
    <div><p class="kicker">صفحهٔ اول / شکار زیرقیمت‌ها</p>
      <h1><span class="mark"><span class="outline-number" id="heroCountNum">۰</span> فرصت</span> در آگهی‌های امروز؛ هر کدام دست‌کم <span class="mark"><span class="outline-number" id="heroMinNum">۰</span>٪</span> زیر قیمت همتای خودش</h1>
      <p class="lede">قاپ آگهی را جدا از هیاهوی بازار می‌سنجد: قیمت، ویژگی‌ها و نمونه‌های همتا کنار هم قرار می‌گیرند تا موردی که واقعاً ارزش بررسی دارد، زودتر دیده شود.</p>
      <div class="actions"><a class="primary" href="#opportunities">فرصت‌ها را نشانم بده <span aria-hidden="true">←</span></a><a class="text-link" href="#method">قاپ چطور حساب می‌کند؟</a></div>
    </div>
    <aside class="hero-aside"><div><span class="pulse"></span><strong class="outline-number"><span id="cycleCount">۳۰</span>′</strong></div><p>بازار هر سی دقیقه دوباره خوانده و فرصت‌ها از نو رتبه‌بندی می‌شوند.</p></aside>
  </section>

  <section class="wrap section" id="opportunities"><div class="section-head"><div><p class="kicker">خبر اصلی</p><h2>فرصتی با فاصلهٔ روشن از بازار</h2></div><p class="section-note">پیش از هر تصمیم، اصل آگهی و وضعیت واقعی کالا را بررسی کن؛ قاپ فقط نقطهٔ شروع را نشان می‌دهد.</p></div><article class="feature" id="featureCard" aria-live="polite"></article><div class="feature-nav"><div class="feature-dots" id="featureDots" aria-label="انتخاب فرصت شاخص"></div><div class="feature-progress" aria-hidden="true"><span id="featureProgress"></span></div><button class="icon-button" id="featurePause" type="button" aria-pressed="false">مکث</button></div></section>

  <section class="wrap section"><div class="section-head"><div><p class="kicker">ویترین</p><h2>فرصت‌های دیگر، بدون شلوغی</h2></div><p class="section-note">هر کارت فقط اطلاعاتی را نشان می‌دهد که برای تصمیم اول لازم است: فاصله از همتا، تعداد مقایسه و درجهٔ اطمینان.</p></div><div class="discovery-tools"><label class="search-label" for="dealSearch">جست‌وجو در فرصت‌ها<input class="search" id="dealSearch" type="search" inputmode="search" placeholder="مثلاً تبریز، دنا یا موبایل" autocomplete="off"></label><div class="filter-bar"><div class="tabs" id="tabs" role="group" aria-label="فیلتر سریع شهر و دسته"></div><span class="filter-status" id="filterStatus" aria-live="polite"></span></div></div><div class="cards" id="cards"></div></section>

  <section class="wrap section" id="method"><div class="section-head"><div><p class="kicker">روش قاپ</p><h2>از آگهی خام تا فرصت قابل بررسی</h2></div><p class="section-note">قاپ جای بازدید، کارشناسی یا استعلام را نمی‌گیرد؛ فقط مرحلهٔ پیدا کردن گزینه‌های امیدوارکننده را کوتاه می‌کند.</p></div><div class="method"><article class="step"><span class="num">۱</span><h3>خواندن بازار</h3><p>آگهی‌های تازهٔ ۳۱ مرکز استان در بازارهای ملک، خودرو و کالای دیجیتال جمع می‌شوند.</p></article><article class="step"><span class="num">۲</span><h3>پاک‌سازی</h3><p>آگهی‌های تکراری، بی‌قیمت یا دارای مشخصات ناسازگار از مقایسه کنار می‌روند.</p></article><article class="step"><span class="num">۳</span><h3>ساخت همتا</h3><p>هر مورد فقط با نمونه‌هایی سنجیده می‌شود که از نظر ویژگی‌های کلیدی به آن نزدیک‌اند.</p></article><article class="step"><span class="num">۴</span><h3>محاسبهٔ فاصله</h3><p>قیمت آگهی با میانهٔ همتاها مقایسه و درصد فاصله بدون بزرگ‌نمایی محاسبه می‌شود.</p></article><article class="step"><span class="num">۵</span><h3>سنجش اطمینان</h3><p>تعداد همتاها و پراکندگی قیمت‌ها تعیین می‌کند قاپ چقدر به نتیجه مطمئن باشد.</p></article><article class="step"><span class="num">۶</span><h3>پرچم احتیاط</h3><p>قیمت غیرعادی، توضیح مبهم یا تناقض مشخصات به‌جای پنهان شدن، کنار نتیجه می‌آید.</p></article></div></section>

  <section class="wrap section" id="questions"><div class="section-head"><div><p class="kicker">پرسش‌های پیش از اعتماد</p><h2>شفاف، همان‌قدر که لازم است</h2></div></div><div class="faq"><details open><summary>آیا هر مورد زیرقیمت، معاملهٔ خوبی است؟</summary><p>نه. زیرقیمت بودن فقط نقطهٔ شروع بررسی است. اصالت آگهی، سلامت فنی، سند، بدهی، شرایط انتقال و علت فروش باید جداگانه بررسی شوند.</p></details><details><summary>«اطمینان بالا» یعنی چه؟</summary><p>یعنی برای مقایسه، همتای کافی وجود داشته و قیمت آن‌ها پراکندگی غیرعادی نداشته است؛ نه اینکه خود کالا یا فروشنده تأیید شده باشد.</p></details><details><summary>چرا یک آگهی ممکن است ناپدید شود؟</summary><p>ممکن است حذف یا فروخته شده باشد، قیمتش تغییر کند یا با ورود دادهٔ تازه دیگر زیر آستانهٔ فرصت قرار نگیرد.</p></details><details><summary>آیا قاپ به آگهی‌دهنده وابسته است؟</summary><p>رتبه‌بندی مستقل و بر اساس مقایسهٔ داده‌ها نمایش داده شده است؛ نمایش در فهرست به‌معنای توصیه یا تضمین معامله نیست.</p></details></div></section>

  <div class="promo"><div class="promo-box"><div><strong>خبرهای مهم را هم <span class="mark">از دست نده</span></strong><p>کانال تلگرامی خبراتور — گزیدهٔ مهم‌ترین خبرهای ایران و جهان</p></div><a href="https://t.me/khabarator" target="_blank" rel="noopener">عضویت در خبراتور</a></div></div>
</main>
{FOOT}
<script>
window.PAGE_DEALS = [];
</script>
<script>
{SHARED_JS}
</script>
<script>
(function(){
  var ICONS = {ICONS_JS};
  function icon(type){ return '<svg viewBox="0 0 96 96" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round" aria-hidden="true">' + (ICONS[type] || ICONS.home) + '</svg>'; }
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var cardsEl = document.getElementById('cards'), featureEl = document.getElementById('featureCard');
  var currentFilter = 'all', currentKind = 'all', query = '', featureIndex = 0, featureTimer = null, featurePaused = reduceMotion;

  function shortTitle(t){ return t.length > 30 ? t.slice(0, 30) + '…' : t; }

  function renderTicker(data){
    var top = data.slice().sort(function(a, b){ return b.pct_below_fair - a.pct_below_fair; }).slice(0, 6);
    var items = top.map(function(d){ return '<span>' + d.city + ' · ' + shortTitle(d.title) + ' · ' + faNum(dealDiscount(d)) + '٪ پایین‌تر</span>'; }).join('<i class="dot"></i>');
    var run = '<div class="ticker-run"><b>فرصت تازه</b><i class="dot"></i>' + items + '<i class="dot"></i><span>رصد ۳۱ مرکز استان · چرخهٔ ۳۰ دقیقه‌ای</span></div>';
    document.getElementById('tickerTrack').innerHTML = run + run.replace('ticker-run', 'ticker-run" aria-hidden="true');
  }

  function animateNumber(id, target, duration){
    var el = document.getElementById(id); if (!el) return;
    if (reduceMotion){ el.textContent = faNum(target); return; }
    var start = null;
    function tick(now){ if (!start) start = now; var p = Math.min((now - start) / duration, 1); var e = 1 - Math.pow(1 - p, 3); el.textContent = faNum(Math.round(target * e)); if (p < 1) requestAnimationFrame(tick); }
    requestAnimationFrame(tick);
  }

  function meter(d){
    var pct = d.fair_price ? Math.max(0, Math.min(100, Math.round(d.price / d.fair_price * 100))) : 100;
    return '<div class="meter" aria-label="قیمت آگهی ' + faNum(pct) + ' درصد قیمت همتا است"><div class="meter-labels"><span>آگهی: ' + faPrice(d.price) + ' تومان</span><span>همتا: ' + faPrice(d.fair_price) + ' تومان</span></div><div class="meter-track"><div class="meter-fill" style="width:' + pct + '%"></div></div></div>';
  }
  function dealBar(d){
    var pct = dealDiscount(d);
    return '<div class="deal-bar" aria-label="فاصله از قیمت همتا ' + faNum(pct) + ' درصد"><div class="deal-bar-head"><span>فاصله از همتا</span><strong>' + faNum(pct) + '٪ زیر بازار</strong></div><div class="deal-bar-track"><div class="deal-bar-fill" style="width:' + Math.min(100, pct * 3) + '%"></div></div></div>';
  }
  function metaRow(d){ return '<div class="meta"><span>' + d.cat_fa + '</span><span>' + (d.district || d.city) + '</span></div>'; }
  function confRow(d){ return '<div class="confidence">' + faNum(d.n_comps) + ' نمونهٔ همتا · اطمینان ' + dealConf(d.n_comps) + '</div>'; }

  function renderFeature(){
    var tops = window.PAGE_DEALS.slice().sort(function(a, b){ return b.pct_below_fair - a.pct_below_fair; }).slice(0, 3);
    if (!tops.length){ featureEl.innerHTML = '<p class="empty" style="padding:40px">فعلاً آگهی زیرقیمتی ثبت نشده.</p>'; return; }
    var d = tops[featureIndex % tops.length], disc = dealDiscount(d);
    var badge = d.tier === 'golden' ? 'فرصت طلایی' : 'فرصت';
    featureEl.innerHTML = '<div class="visual">' + bookmarkHTML(d) + icon(d.icon) + '<div class="stamp">' + faNum(disc) + '٪<br>پایین‌تر</div></div>'
      + '<div class="feature-copy"><div class="meta"><span>' + d.cat_fa + '</span><span>' + d.city + '</span><span>' + badge + '</span></div>'
      + '<h3>' + d.title + '</h3><div class="price">' + faPrice(d.price) + ' تومان</div>'
      + meter(d) + dealBar(d) + confRow(d)
      + '</div>';
    document.getElementById('featureDots').innerHTML = tops.map(function(item, i){
      return '<button class="feature-dot" type="button" data-feature="' + i + '" aria-label="نمایش فرصت ' + faNum(i + 1) + '" aria-pressed="' + (i === featureIndex % tops.length) + '"></button>';
    }).join('');
    restartProgress();
  }
  function restartProgress(){ var bar = document.getElementById('featureProgress'); bar.style.animation = 'none'; void bar.offsetWidth; bar.style.animation = featurePaused ? 'none' : ''; }
  function startFeatureTimer(){ clearInterval(featureTimer); if (!featurePaused){ featureTimer = setInterval(function(){ featureIndex = (featureIndex + 1) % 3; renderFeature(); }, 7000); } }
  function selectFeature(i){ featureIndex = i; renderFeature(); startFeatureTimer(); }
  document.getElementById('featureDots').addEventListener('click', function(e){ var b = e.target.closest('[data-feature]'); if (b) selectFeature(Number(b.getAttribute('data-feature'))); });
  document.getElementById('featurePause').addEventListener('click', function(){ featurePaused = !featurePaused; this.setAttribute('aria-pressed', featurePaused); this.textContent = featurePaused ? 'پخش' : 'مکث'; restartProgress(); startFeatureTimer(); });

  function buildTabs(data){
    var cities = {}, cats = {};
    data.forEach(function(d){ cities[d.city] = (cities[d.city] || 0) + 1; cats[d.category] = (cats[d.category] || 0) + 1; });
    var topCities = Object.keys(cities).sort(function(a, b){ return cities[b] - cities[a]; }).slice(0, 6);
    var catOrder = ['house_sell', 'house_rent', 'car', 'motorcycle', 'mobile', 'commercial_sell', 'commercial_rent'];
    var catList = catOrder.filter(function(c){ return cats[c]; });
    var tabs = '<button class="tab" data-kind="all" data-filter="all" aria-pressed="true">همه</button>'
      + topCities.map(function(c){ return '<button class="tab" data-kind="city" data-filter="' + c + '" aria-pressed="false">' + c + '</button>'; }).join('')
      + catList.map(function(c){ var label = (window.CAT_FA_MAP || {})[c] || c; return '<button class="tab" data-kind="category" data-filter="' + c + '" aria-pressed="false">' + label + '</button>'; }).join('');
    document.getElementById('tabs').innerHTML = tabs;
    document.querySelectorAll('#tabs .tab').forEach(function(btn){
      btn.addEventListener('click', function(){
        document.querySelectorAll('#tabs .tab').forEach(function(b){ b.setAttribute('aria-pressed', 'false'); });
        btn.setAttribute('aria-pressed', 'true');
        currentFilter = btn.getAttribute('data-filter'); currentKind = btn.getAttribute('data-kind');
        renderCards(true);
      });
    });
  }

  function matchingItems(){
    var needle = query.trim();
    return window.PAGE_DEALS.filter(function(d){
      var ok = currentFilter === 'all' || (currentKind === 'city' ? d.city === currentFilter : d.category === currentFilter);
      var hay = d.title + ' ' + d.city + ' ' + (d.district || '') + ' ' + d.cat_fa;
      return ok && (!needle || hay.indexOf(needle) > -1);
    });
  }
  function renderCards(animateNow){
    var items = matchingItems();
    cardsEl.innerHTML = items.length ? items.map(function(d, i){
      var pct = dealDiscount(d);
      return '<article class="card" style="--delay:' + (i * 110) + 'ms">' + bookmarkHTML(d)
        + '<div class="card-main">'
        + '<div class="card-icon">' + icon(d.icon) + '</div>' + metaRow(d)
        + '<h3><span class="mark">' + faNum(pct) + '٪</span> زیر قیمت همتا</h3>'
        + '<div class="deal-title">' + d.title + '</div>'
        + meter(d) + dealBar(d) + confRow(d)
        + '</div></article>';
    }).join('') : '<p class="empty">فرصتی با این جست‌وجو و فیلتر پیدا نشد.</p>';
    document.getElementById('filterStatus').textContent = faNum(items.length) + ' فرصت نمایش داده شد';
    if (animateNow && !reduceMotion){ cardsEl.classList.remove('is-staggering'); void cardsEl.offsetWidth; cardsEl.classList.add('is-staggering'); }
  }
  document.getElementById('dealSearch').addEventListener('input', function(){ query = this.value; renderCards(true); });

  fetch('deals.json').then(function(r){ return r.json(); }).then(function(j){
    var ds = j.deals || [];
    window.PAGE_DEALS = ds;
    renderTicker(ds);
    var minPct = ds.length ? Math.min.apply(null, ds.map(dealDiscount)) : 0;
    animateNumber('heroCountNum', ds.length, 720);
    animateNumber('heroMinNum', minPct, 950);
    buildTabs(ds);
    renderFeature(); renderCards(false); renderSaved(); startFeatureTimer();
    var u = document.getElementById('updated'); if (u && j.updated_fa) u.textContent = 'آخرین به‌روزرسانی: ' + j.updated_fa;
    if (!reduceMotion && 'IntersectionObserver' in window){
      var obs = new IntersectionObserver(function(es){ if (es[0].isIntersecting){ cardsEl.classList.add('is-staggering'); obs.disconnect(); } }, { threshold: 0.16 });
      obs.observe(cardsEl);
    }
  }).catch(function(){
    document.getElementById('cards').innerHTML = '<p class="empty">خطا در بارگذاری فرصت‌ها؛ لطفاً صفحه را تازه کن.</p>';
  });
})();
</script>
</body>
</html>
"""


PAGE_HTML = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<meta name="color-scheme" content="light dark"/>
<title>{TITLE} | قاپ</title>
<meta name="description" content="{DESC}"/>
<link rel="icon" href="data:,"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800;900&display=swap" rel="stylesheet"/>
<style>{STYLE}</style>
</head>
<body>
{MASTHEAD}
{EDITION}
{CHIPS}
<main>
<div class="wrap page-head"><span class="kicker">{EYEBROW}</span><h1>{H1}</h1><p class="intro">{INTRO}</p></div>
<section class="wrap section"><div class="cards">{CARDS}</div></section>
</main>
{FOOT}
<script>
window.PAGE_DEALS = {PAGE_DEALS_JSON};
</script>
<script>
{SHARED_JS}
</script>
</body>
</html>
"""


def build(db_path, out_path, limit=80):
    con = sqlite3.connect(db_path)
    cities = [r[0] for r in con.execute(
        "SELECT DISTINCT city FROM ads WHERE tier IN ('golden','opportunity') AND city IS NOT NULL").fetchall()]
    cats = [("car" if r[0] == "cars" else r[0]) for r in con.execute(
        "SELECT DISTINCT category FROM ads WHERE tier IN ('golden','opportunity')").fetchall()
        if ("car" if r[0] == "cars" else r[0]) in CATS]
    con.close()
    cities.sort()
    cats.sort(key=lambda c: list(CATS).index(c))

    updated_fa = tehran_now_fa()
    urls = [f"{SITE_URL}/"]
    os.makedirs(out_path, exist_ok=True)
    os.makedirs(os.path.join(out_path, "city"), exist_ok=True)
    os.makedirs(os.path.join(out_path, "cat"), exist_ok=True)

    deals = load_deals(db_path, limit)
    payload = {"deals": deals, "updated_fa": updated_fa, "count": len(deals)}
    with open(os.path.join(out_path, "deals.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    idx = INDEX_HTML.replace("{STYLE}", STYLE)
    idx = idx.replace("{MASTHEAD}", masthead_html())
    idx = idx.replace("{EDITION}", edition_html(updated_fa))
    idx = idx.replace("{FOOT}", FOOT_HTML)
    idx = idx.replace("{ICONS_JS}", json.dumps(ICON_PATHS))
    idx = idx.replace("window.PAGE_DEALS = [];",
                      "window.PAGE_DEALS = [];\nwindow.CAT_FA_MAP = " + json.dumps(CAT_FA) + ";")
    idx = idx.replace("{SHARED_JS}", SHARED_JS)
    idx = idx.replace('id="updated"></span>',
                      'id="updated">آخرین به‌روزرسانی: ' + updated_fa + '</span>')
    with open(os.path.join(out_path, "index.html"), "w", encoding="utf-8") as f:
        f.write(idx)

    for city in cities:
        cdeals = load_deals(db_path, 60, city=city)
        slug = city_slug(city)
        cards = "".join(card_static_html(d) for d in cdeals) or \
            '<div class="empty-box">فعلاً آگهی زیرقیمتی در این شهر ثبت نشده.</div>'
        pg = PAGE_HTML.replace("{TITLE}", f"فرصت‌های {city}")
        pg = pg.replace("{DESC}", f"آگهی‌های زیرقیمت {city} در قاپ")
        pg = pg.replace("{STYLE}", STYLE)
        pg = pg.replace("{MASTHEAD}", masthead_html(prefix="../", index_mode=False))
        pg = pg.replace("{EDITION}", edition_html(updated_fa))
        pg = pg.replace("{CHIPS}", chips_html(cities, cats, prefix="../", active_city=city))
        pg = pg.replace("{FOOT}", FOOT_HTML)
        pg = pg.replace("{EYEBROW}", "فرصت‌های شهری")
        pg = pg.replace("{H1}", f"فرصت‌های زیرقیمت {city}")
        pg = pg.replace("{INTRO}", f"{fa_num(len(cdeals))} آگهی زیرقیمت در {city} — با مقایسه قیمت آگهی و برآورد منصفانه بازار.")
        pg = pg.replace("{CARDS}", cards)
        pg = pg.replace("{PAGE_DEALS_JSON}", json.dumps(cdeals, ensure_ascii=False))
        pg = pg.replace("{SHARED_JS}", SHARED_JS)
        pg = pg.replace('id="updated"></span>',
                        'id="updated">آخرین به‌روزرسانی: ' + updated_fa + '</span>')
        with open(os.path.join(out_path, "city", f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(pg)
        urls.append(f"{SITE_URL}/city/{slug}.html")

    for cat in cats:
        code = cat if cat != "cars" else "car"
        cdeals = load_deals(db_path, 60, category=cat)
        slug = CATS[code][0]
        cards = "".join(card_static_html(d) for d in cdeals) or \
            '<div class="empty-box">فعلاً آگهی زیرقیمتی در این دسته ثبت نشده.</div>'
        pg = PAGE_HTML.replace("{TITLE}", CATS[code][1])
        pg = pg.replace("{DESC}", CATS[code][2])
        pg = pg.replace("{STYLE}", STYLE)
        pg = pg.replace("{MASTHEAD}", masthead_html(prefix="../", index_mode=False))
        pg = pg.replace("{EDITION}", edition_html(updated_fa))
        pg = pg.replace("{CHIPS}", chips_html(cities, cats, prefix="../", active_cat=code))
        pg = pg.replace("{FOOT}", FOOT_HTML)
        pg = pg.replace("{EYEBROW}", "فرصت‌های دسته‌بندی")
        pg = pg.replace("{H1}", f"فرصت‌های {CATS[code][1]}")
        pg = pg.replace("{INTRO}", f"{fa_num(len(cdeals))} آگهی زیرقیمت در دسته {CATS[code][1]}.")
        pg = pg.replace("{CARDS}", cards)
        pg = pg.replace("{PAGE_DEALS_JSON}", json.dumps(cdeals, ensure_ascii=False))
        pg = pg.replace("{SHARED_JS}", SHARED_JS)
        pg = pg.replace('id="updated"></span>',
                        'id="updated">آخرین به‌روزرسانی: ' + updated_fa + '</span>')
        with open(os.path.join(out_path, "cat", f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(pg)
        urls.append(f"{SITE_URL}/cat/{slug}.html")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sm = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>")
    with open(os.path.join(out_path, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sm)
    with open(os.path.join(out_path, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    print(f"exported {len(deals)} deals -> {out_path}/ "
          f"({len(cities)} city pages, {len(cats)} cat pages, {len(urls)} urls, updated {updated_fa})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()
    build(args.db, args.out, args.limit)


if __name__ == "__main__":
    main()

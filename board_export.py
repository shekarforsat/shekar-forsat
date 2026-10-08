#!/usr/bin/env python3
"""خروجی استاتیک برد «قاپ» برای هاست رایگان (GitHub Pages).

از deals.db می‌خواند و می‌سازد:
  site/index.html        برد اصلی
  site/city/<slug>.html  صفحه سئو برای هر شهر (۳۱ مرکز استان)
  site/cat/<slug>.html   صفحه سئو برای هر دسته
  site/deals.json        دیتای خام برد
  site/sitemap.xml       نقشه سایت برای گوگل
  site/robots.txt

بدون هیچ وابستگی خارجی (فقط استاندارد پایتون) تا در GitHub Actions هم بی‌نقص اجرا شود.
آدرس پایه سایت از متغیر محیطی SITE_URL خوانده می‌شود.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

FA = "۰۱۲۳۴۵۶۷۸۹"
SITE_URL = os.environ.get("SITE_URL", "https://shekarforsat.github.io/shekar-forsat").rstrip("/")


def fa_num(n) -> str:
    return str(n).translate(str.maketrans("0123456789", FA))


# --- تبدیل گریگوری به جلالی (الگوریتم چرخه‌ای استاندارد) ---
def gregorian_to_jalali(gy: int, gm: int, gd: int):
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


def tehran_now_fa() -> str:
    now = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{fa_num(jd)} {JMONTHS[jm]} {fa_num(jy)} — ساعت {fa_num(f'{now.hour:02d}:{now.minute:02d}')}"


def today_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime("%Y-%m-%d")


# --- شهرها: نام فارسی -> اسلاگ لاتین ---
CITY_SLUG = {
    "تهران": "tehran", "کرج": "karaj", "مشهد": "mashhad", "اصفهان": "isfahan",
    "تبریز": "tabriz", "شیراز": "shiraz", "اهواز": "ahvaz", "قم": "qom",
    "کرمانشاه": "kermanshah", "ارومیه": "urmia", "رشت": "rasht", "کرمان": "kerman",
    "یزد": "yazd", "بندرعباس": "bandar-abbas", "زاهدان": "zahedan", "همدان": "hamedan",
    "ساری": "sari", "گرگان": "gorgan", "قزوین": "qazvin", "اراک": "arak",
    "زنجان": "zanjan", "سنندج": "sanandaj", "خرم‌آباد": "khorramabad", "خرماباد": "khorramabad",
    "ایلام": "ilam", "بوشهر": "bushehr", "بیرجند": "birjand", "شهرکرد": "shahrekord",
    "یاسوج": "yasuj", "سمنان": "semnan", "بجنورد": "bojnurd", "اردبیل": "ardabil",
}


def city_slug(name: str) -> str:
    key = (name or "").replace("‌", "").replace(" ", "")
    for k, v in CITY_SLUG.items():
        if k.replace("‌", "") == key:
            return v
    return "other"


# --- دسته‌ها: کد -> (اسلاگ، نام فارسی، عبارت سئو) ---
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


def load_deals(db_path: str, limit: int = 80, city: str | None = None,
               category: str | None = None) -> list[dict]:
    con = sqlite3.connect(db_path)
    q = """SELECT token,title,category,city,district,price,img,tier,discount,first_seen
           FROM ads WHERE tier IN ('golden','opportunity') AND price>0"""
    params: list = []
    if city:
        q += " AND city=?"; params.append(city)
    if category:
        q += " AND category=?"; params.append(category)
    q += """ ORDER BY CASE tier WHEN 'golden' THEN 0 ELSE 1 END, discount DESC, first_seen DESC
             LIMIT ?"""
    params.append(limit)
    rows = con.execute(q, params).fetchall()
    con.close()
    deals = []
    for token, title, category, city, district, price, img, tier, discount, _ in rows:
        discount = discount or 0.0
        fair = round(price / (1 - discount)) if discount > 0 else price
        deals.append({
            "token": token, "title": title or "",
            "category": "car" if category == "cars" else (category or ""),
            "city": city or "", "district": district or "",
            "price": price, "fair": fair,
            "discount": round(discount, 4), "tier": tier, "img": img or "",
        })
    return deals


def card_html(d: dict) -> str:
    t = html.escape(d["title"])
    badge = ("💎 فرصت طلایی" if d["tier"] == "golden" else "🔥 فرصت")
    ai = '<span class="aipick">🤖 شکار هوش مصنوعی</span>' if d["tier"] == "golden" else ""
    cat = CAT_FA.get(d["category"], "")
    loc = " · ".join(x for x in [d["city"], d["district"]] if x)
    img = (f'<img src="{html.escape(d["img"])}" loading="lazy" alt="{t}">'
           if d["img"] else "")
    return f"""
  <a class="card {d['tier']}" href="https://divar.ir/v/{html.escape(d['token'])}" target="_blank" rel="noopener">
    <span class="badge {d['tier']}">{badge} {fa_num(round(d['discount']*100))}٪ زیر قیمت</span>
    {img}
    <div class="body"><p class="title">{t}</p>
    <div class="meta">{html.escape(cat)}{' · ' if cat and loc else ''}{html.escape(loc)}</div>
    <div class="price">{fa_num(f'{d["price"]:,}')} تومان</div>
    <div class="disc">قیمت منصفانه: {fa_num(f'{d["fair"]:,}')} تومان</div>{ai}</div>
  </a>"""


STYLE = """<style>
:root{--gold:#b8860b;--green:#2e7d32;--ink:#1a1a1a;--mut:#666;--bg:#f7f5f0}
*{box-sizing:border-box}body{font-family:Tahoma,Arial;background:var(--bg);color:var(--ink);margin:0}
header{background:#111;color:#fff;padding:18px 16px;text-align:center}
header h1{margin:0;font-size:22px}header p{margin:6px 0 0;color:#bbb;font-size:13px}
header a{color:#ffd75e}
.live{display:inline-block;background:#1b5e20;color:#fff;font-size:12px;padding:3px 10px;border-radius:12px;margin-top:8px}
.nav{display:flex;gap:8px;justify-content:center;padding:12px;flex-wrap:wrap;background:#fff;border-bottom:1px solid #eee}
.nav a{color:var(--ink);text-decoration:none;font-size:13px;border:1px solid #ddd;border-radius:16px;padding:5px 12px}
.nav a:hover{border-color:#111}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;padding:16px;max-width:1200px;margin:0 auto}
.card{background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.07);position:relative}
.card img{width:100%;height:170px;object-fit:cover;background:#eee}
.badge{position:absolute;top:10px;right:10px;color:#fff;font-size:12px;font-weight:bold;padding:5px 12px;border-radius:20px}
.badge.golden{background:var(--gold)}.badge.opp,.badge.opportunity{background:var(--green)}
.body{padding:12px 14px}.title{font-size:14px;font-weight:bold;margin:0 0 8px;line-height:1.7}
.meta{color:var(--mut);font-size:12px;margin-bottom:8px}
.price{font-size:17px;font-weight:bold}
.disc{font-size:12px;color:var(--green);font-weight:bold}
.card.golden{outline:2px solid var(--gold)}
a.card{text-decoration:none;color:inherit;display:block}
.empty{text-align:center;color:var(--mut);padding:60px 20px}
.updated{text-align:center;color:var(--mut);font-size:12px;padding:0 0 8px}
.note{text-align:center;color:var(--mut);font-size:11px;padding:0 16px 24px;max-width:700px;margin:0 auto;line-height:1.9}
.intro{max-width:800px;margin:0 auto;padding:14px 18px;font-size:14px;line-height:2;color:#333}
h2.sec{max-width:1200px;margin:6px auto 0;padding:0 18px;font-size:17px}
footer{text-align:center;color:var(--mut);font-size:12px;padding:18px;border-top:1px solid #eee;background:#fff}
.promo{display:flex;align-items:center;gap:12px;max-width:1200px;margin:14px auto 0;padding:12px 18px;background:linear-gradient(135deg,#0E2E34,#0A7F6E);color:#fff;border-radius:14px;text-decoration:none}
.promo .emj{font-size:26px}
.promo b{font-size:15px}
.promo .txt{font-size:12.5px;opacity:.92;display:block;margin-top:2px}
.promo .cta{margin-inline-start:auto;background:#fff;color:#0E2E34;font-size:13px;font-weight:bold;padding:7px 18px;border-radius:20px;white-space:nowrap}
.aihero{position:relative;max-width:1200px;margin:14px auto 0;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.25)}
.aihero img{width:100%;display:block}
.aihero .ov{position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.78) 0%,rgba(0,0,0,.15) 55%,rgba(0,0,0,.05) 100%);display:flex;flex-direction:column;justify-content:flex-end;padding:22px}
.aihero .ov h2{color:#ffd75e;margin:0;font-size:20px}
.aihero .ov p{color:#fff;margin:6px 0 0;font-size:13.5px;line-height:1.9}
.aihero .aibadge{align-self:flex-start;background:rgba(255,215,94,.15);border:1px solid #ffd75e;color:#ffd75e;font-size:12px;padding:4px 12px;border-radius:14px;margin-bottom:8px}
.aipick{display:inline-block;background:#111;color:#ffd75e;font-size:11px;padding:2px 10px;border-radius:10px;margin-top:6px}
.hl{background:linear-gradient(180deg,transparent 62%,#ffd75e 62%,#ffd75e 96%,transparent 96%);padding:0 3px}
header .hl{background:linear-gradient(180deg,transparent 55%,#ffd75e 55%,#ffd75e 95%,transparent 95%);color:#fff;padding:0 6px}
</style>"""

PROMO_BANNER = """<a class="promo" href="https://t.me/khabarator" target="_blank" rel="noopener">
<span class="emj">🗞️</span>
<span><b>خبراتور</b><span class="txt">ما خبر رو از شایعه جدا می‌کنیم — عضو کانال تلگرام شو</span></span>
<span class="cta">عضویت</span></a>"""

DISCLAIMER = ("درصدهای «زیر قیمت» برآورد ما از قیمت منصفانهٔ هر محله/مدل‌اند و ممکن است "
              "با واقعیت بازار اختلاف داشته باشند؛ قبل از هر تصمیمی، خودتان آگهی و محله را بررسی کنید.")


def nav_html(cities: list[str], cats: list[str]) -> str:
    city_links = " ".join(
        f'<a href="{SITE_URL}/city/{city_slug(c)}.html">{html.escape(c)}</a>' for c in cities)
    cat_links = " ".join(
        f'<a href="{SITE_URL}/cat/{CATS[c][0]}.html">{html.escape(CATS[c][1])}</a>' for c in cats)
    return f'<nav class="nav"><a href="{SITE_URL}/">🏠 همه</a>{cat_links}<br>{city_links}</nav>'


def page_shell(title: str, desc: str, url: str, h1: str, sub: str,
               body: str, nav: str, updated_fa: str) -> str:
    return f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{html.escape(url)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
{STYLE}</head><body>
<header><h1>{h1}</h1><p>{html.escape(sub)}</p><span class="live">● فعال</span></header>
{PROMO_BANNER}
{nav}
{body}
<div class="updated">آخرین به‌روزرسانی: {html.escape(updated_fa)}</div>
<p class="note">{html.escape(DISCLAIMER)}</p>
<footer>قاپ — زیرقیمت‌های واقعی دیوار، هر ۳۰ دقیقه تازه‌سازی می‌شود.</footer>
</body></html>"""


def build_city_page(city: str, deals: list[dict], nav: str, updated_fa: str) -> str:
    gold = sum(1 for d in deals if d["tier"] == "golden")
    title = f"زیرقیمت‌های دیوار {city} | قاپ"
    desc = (f"آگهی‌های زیر قیمت واقعی دیوار {city} — آپارتمان، خودرو، موبایل و ملک تجاری. "
            f"{fa_num(len(deals))} فرصت فعال ({fa_num(gold)} طلایی)، به‌روزرسانی هر ۳۰ دقیقه.")
    cards = "".join(card_html(d) for d in deals) or '<div class="empty">هنوز فرصت تازه‌ای ثبت نشده — چند دقیقه دیگر سر بزن.</div>'
    body = (f'<div class="intro">خونه، ماشین، گوشی یا مغازه زیر قیمت در <b>{html.escape(city)}</b> می‌خوای؟ '
            f'این صفحه آگهی‌های دیوار {html.escape(city)} را که از قیمت منصفانهٔ محله/مدل پایین‌ترند، هر ۳۰ دقیقه '
            f'تازه می‌کند. روی هر کارت بزن تا آگهی اصلی در دیوار باز شود.</div>'
            f'<h2 class="sec">فرصت‌های امروز {html.escape(city)} ({fa_num(len(deals))})</h2>'
            f'<div class="grid">{cards}</div>')
    return page_shell(title, desc, f"{SITE_URL}/city/{city_slug(city)}.html",
                      f"🎯 زیرقیمت‌های دیوار <span class=\"hl\">{html.escape(city)}</span>",
                      f"{fa_num(len(deals))} فرصت فعال — به‌روزرسانی خودکار هر ۳۰ دقیقه",
                      body, nav, updated_fa)


def build_cat_page(cat: str, deals: list[dict], nav: str, updated_fa: str) -> str:
    slug, fa_name, seo_phrase = CATS[cat]
    title = f"{seo_phrase} در دیوار | قاپ"
    desc = (f"{seo_phrase} — آگهی‌های واقعی دیوار که از قیمت منصفانه پایین‌ترند، در ۳۱ مرکز استان. "
            f"به‌روزرسانی هر ۳۰ دقیقه.")
    cards = "".join(card_html(d) for d in deals) or '<div class="empty">هنوز فرصت تازه‌ای ثبت نشده — چند دقیقه دیگر سر بزن.</div>'
    body = (f'<div class="intro"><b>{html.escape(fa_name)}</b> زیر قیمت در دیوار؟ این صفحه آگهی‌هایی را نشان می‌دهد '
            f'که از قیمت منصفانهٔ بازار پایین‌ترند — در همهٔ ۳۱ مرکز استان، با تازه‌سازی هر ۳۰ دقیقه.</div>'
            f'<h2 class="sec">{html.escape(fa_name)} زیر قیمت ({fa_num(len(deals))})</h2>'
            f'<div class="grid">{cards}</div>')
    return page_shell(title, desc, f"{SITE_URL}/cat/{slug}.html",
                      f"🎯 <span class=\"hl\">{html.escape(seo_phrase)}</span>",
                      f"{fa_num(len(deals))} فرصت فعال در ۳۱ مرکز استان",
                      body, nav, updated_fa)


INDEX_HTML = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>قاپ | زیرقیمت‌های واقعی دیوار در ۳۱ مرکز استان</title>
<meta name="description" content="آگهی‌های زیر قیمت واقعی دیوار — آپارتمان، خودرو، موتورسیکلت، موبایل و ملک تجاری در ۳۱ مرکز استان ایران. به‌روزرسانی خودکار هر ۳۰ دقیقه.">
<meta property="og:title" content="قاپ | زیرقیمت‌های واقعی دیوار">
<meta property="og:description" content="آپارتمان، خودرو، موبایل و ملک تجاری زیر قیمت — ۳۱ مرکز استان، هر ۳۰ دقیقه تازه‌سازی.">
<meta property="og:type" content="website">
""" + STYLE + """</head><body>
<header><h1>🎯 <span class="hl">قاپ</span></h1><p>فرصت رو قاپ بزن — زیرقیمت‌های واقعی دیوار در ۳۱ مرکز استان — هر ۳۰ دقیقه تازه‌سازی</p><span class="live">● فعال</span></header>
<div class="aihero"><img src="assets/ai-hero.jpg" alt="هوش مصنوعی قاپ"><div class="ov"><span class="aibadge">🤖 قدرت‌گرفته از هوش مصنوعی</span><h2>هوش مصنوعی قاپ، <span class="hl">فرصت‌های طلایی</span> را شکار می‌کند</h2><p>موتور هوشمند ما هر ۳۰ دقیقه هزاران آگهی دیوار را می‌خواند، قیمت هر محله و مدل را می‌سنجد و فقط واقعی‌ترین زیرقیمت‌ها را اینجا می‌گذارد.</p></div></div>
""" + PROMO_BANNER + """
__NAV__
<div class="filters" style="display:flex;gap:8px;justify-content:center;padding:14px;flex-wrap:wrap">
<button data-f="all" class="on" style="border:1px solid #ccc;background:#fff;border-radius:20px;padding:8px 18px;font-family:inherit;cursor:pointer">همه</button><button data-f="golden" style="border:1px solid #ccc;background:#fff;border-radius:20px;padding:8px 18px;font-family:inherit;cursor:pointer">💎 فرصت طلایی</button><button data-f="opportunity" style="border:1px solid #ccc;background:#fff;border-radius:20px;padding:8px 18px;font-family:inherit;cursor:pointer">🔥 فرصت</button>
</div>
<div class="grid" id="grid"></div>
<div class="updated" id="updated"></div>
<p class="note">__DISCLAIMER__</p>
<footer style="text-align:center;color:#666;font-size:12px;padding:18px;border-top:1px solid #eee;background:#fff">قاپ — زیرقیمت‌های واقعی دیوار، هر ۳۰ دقیقه تازه‌سازی می‌شود.</footer>
<script>
const FA="۰۱۲۳۴۵۶۷۸۹", fa=n=>String(n).replace(/\\d/g,d=>FA[d]);
const CAT={house_sell:"🏠 فروش",house_rent:"🔑 اجاره",car:"🚗 خودرو",motorcycle:"🏍 موتور",mobile:"📱 موبایل",commercial_sell:"🏢 تجاری",commercial_rent:"🏢 اجاره تجاری"};
let all=[],f="all";
async function load(){
  const r=await fetch("deals.json"); const j=await r.json(); all=j.deals;
  document.getElementById("updated").textContent="آخرین به‌روزرسانی: "+j.updated_fa+" — "+fa(j.count)+" آگهی زیرقیمت";
  render();
}
function render(){
  const g=document.getElementById("grid");
  const list=all.filter(d=>f==="all"?true:d.tier===f);
  if(!list.length){g.innerHTML='<div class="empty">هنوز فرصت تازه‌ای ثبت نشده — چند دقیقه دیگر سر بزن.</div>';return;}
  g.innerHTML=list.map(d=>`
  <a class="card ${d.tier}" href="https://divar.ir/v/${d.token}" target="_blank" rel="noopener">
    <span class="badge ${d.tier}">${d.tier==="golden"?"💎 فرصت طلایی":"🔥 فرصت"} ${fa(Math.round(d.discount*100))}٪ زیر قیمت</span>
    ${d.img?`<img src="${d.img}" loading="lazy" alt="">`:""}
    <div class="body"><p class="title"></p>
    <div class="meta">${CAT[d.category]||""} · ${d.city||""} ${d.district||""}</div>
    <div class="price">${fa(d.price.toLocaleString("en"))} تومان</div>
    <div class="disc">قیمت منصفانه: ${fa(d.fair.toLocaleString("en"))} تومان</div></div>
  </a>`).join("");
  document.querySelectorAll(".title").forEach((el,i)=>{el.textContent=list[i].title;});
}
document.querySelectorAll(".filters button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".filters button").forEach(x=>x.classList.remove("on"));
  b.classList.add("on"); f=b.dataset.f; render();
});
load();
</script></body></html>
"""


def build_sitemap(urls: list[str], date_iso: str) -> str:
    items = "\n".join(
        f"  <url><loc>{html.escape(u)}</loc><lastmod>{date_iso}</lastmod>"
        f"<changefreq>daily</changefreq><priority>{'1.0' if u.rstrip('/')==SITE_URL else '0.8'}</priority></url>"
        for u in urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{items}
</urlset>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/home/hatch/workspace/divar-deals/deals.db")
    ap.add_argument("--out", default="/home/hatch/workspace/divar-deals/site")
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(f"{args.out}/city", exist_ok=True)
    os.makedirs(f"{args.out}/cat", exist_ok=True)
    os.makedirs(f"{args.out}/assets", exist_ok=True)
    # تصویر هیروی هوش مصنوعی (کنار همین اسکریپت در site-assets/)
    _hero = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site-assets", "ai-hero.jpg")
    if os.path.exists(_hero):
        import shutil
        shutil.copyfile(_hero, f"{args.out}/assets/ai-hero.jpg")
    updated_fa = tehran_now_fa()
    date_iso = today_iso()

    con = sqlite3.connect(args.db)
    cities = [r[0] for r in con.execute(
        "SELECT DISTINCT city FROM ads WHERE tier IN ('golden','opportunity') AND city IS NOT NULL").fetchall()]
    cats = [r[0] for r in con.execute(
        "SELECT DISTINCT category FROM ads WHERE tier IN ('golden','opportunity')").fetchall()
        if r[0] in CATS]
    con.close()
    cities.sort()
    cats.sort(key=lambda c: list(CATS).index(c))

    nav = nav_html(cities, cats)
    urls = [f"{SITE_URL}/"]

    # برد اصلی
    deals = load_deals(args.db, args.limit)
    payload = {"deals": deals, "updated_fa": updated_fa, "count": len(deals)}
    with open(f"{args.out}/deals.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    index = INDEX_HTML.replace("__NAV__", nav).replace("__DISCLAIMER__", html.escape(DISCLAIMER))
    with open(f"{args.out}/index.html", "w", encoding="utf-8") as f:
        f.write(index)

    # صفحات شهری
    for city in cities:
        cdeals = load_deals(args.db, 60, city=city)
        slug = city_slug(city)
        with open(f"{args.out}/city/{slug}.html", "w", encoding="utf-8") as f:
            f.write(build_city_page(city, cdeals, nav, updated_fa))
        urls.append(f"{SITE_URL}/city/{slug}.html")

    # صفحات دسته‌بندی
    for cat in cats:
        cdeals = load_deals(args.db, 60, category=cat)
        slug = CATS[cat][0]
        with open(f"{args.out}/cat/{slug}.html", "w", encoding="utf-8") as f:
            f.write(build_cat_page(cat, cdeals, nav, updated_fa))
        urls.append(f"{SITE_URL}/cat/{slug}.html")

    # sitemap + robots
    with open(f"{args.out}/sitemap.xml", "w", encoding="utf-8") as f:
        f.write(build_sitemap(urls, date_iso))
    with open(f"{args.out}/robots.txt", "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")

    print(f"exported {len(deals)} deals -> {args.out}/ "
          f"({len(cities)} city pages, {len(cats)} cat pages, {len(urls)} urls, updated {updated_fa})")


if __name__ == "__main__":
    main()

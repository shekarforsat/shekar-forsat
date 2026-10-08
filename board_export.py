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
    # تعداد آگهی هر شهر/دسته برای «مقایسه با N آگهی»
    con2 = sqlite3.connect(db_path)
    counts = {(c, k): n for c, k, n in
              con2.execute("SELECT city, category, COUNT(*) FROM ads GROUP BY city, category").fetchall()}
    con2.close()
    deals = []
    for token, title, category, city, district, price, img, tier, discount, _ in rows:
        discount = discount or 0.0
        fair = round(price / (1 - discount)) if discount > 0 else price
        cat = "car" if category == "cars" else (category or "")
        deals.append({
            "token": token, "title": title or "",
            "category": cat,
            "city": city or "", "district": district or "",
            "price": price, "fair": fair,
            "discount": round(discount, 4), "tier": tier, "img": img or "",
            "n": counts.get((city, category), 0),
        })
    return deals


def _conf(n: int) -> str:
    if n >= 50: return "اطمینان بالا"
    if n >= 15: return "اطمینان متوسط"
    return "اطمینان کم"



STYLE = """<style>
:root{
  color-scheme:light dark;
  --paper:#f5f6f8; --surface:#ffffff; --ink:#09172d; --muted:#526075;
  --line:#e3e9f2; --line-strong:#98a6b9;
  --blue:#075ee6; --blue-hover:#004dc4; --blue-soft:#e7efff;
  --green:#08724b; --green-soft:#e5f5ee;
  --gold:#b8860b; --gold-soft:#faf3dd;
  --max:1180px; --shadow:0 22px 60px rgba(17,39,73,.12);
}
@media (prefers-color-scheme:dark){
  :root{
    --paper:#0c111b; --surface:#121a28; --ink:#f5f8fd; --muted:#adb9c9;
    --line:#263449; --line-strong:#56667d;
    --blue:#70a7ff; --blue-hover:#9ac0ff; --blue-soft:#162c50;
    --green:#70d5aa; --green-soft:#12362a;
    --gold:#e3b341; --gold-soft:#2c250f;
    --shadow:0 28px 70px rgba(0,0,0,.34);
  }
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;min-width:320px;overflow-x:hidden;background:var(--paper);color:var(--ink);
  font-family:"Vazirmatn",Tahoma,Arial,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
::selection{background:var(--blue);color:#fff}
.topbar{border-bottom:1px solid var(--line);background:var(--surface)}
.topbar-inner{width:min(calc(100% - 48px),var(--max));margin:0 auto;min-height:64px;
  display:flex;align-items:center;justify-content:space-between;gap:16px}
.brand{font-weight:900;font-size:1.35rem;text-decoration:none;letter-spacing:-.02em}
.brand b{color:var(--blue)}
.live{display:inline-flex;align-items:center;gap:8px;color:var(--muted);font-size:.8rem}
.live i{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px var(--green-soft)}
.hero{padding:clamp(48px,7vw,96px) max(24px,env(safe-area-inset-right)) clamp(56px,8vw,110px) max(24px,env(safe-area-inset-left));
  border-bottom:1px solid var(--line);position:relative;overflow:hidden}
.hero::before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.28;
  background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
  background-size:72px 72px;mask-image:linear-gradient(to left,#000,transparent 62%)}
.hero-inner{position:relative;width:min(100%,var(--max));margin:0 auto;display:grid;
  grid-template-columns:minmax(0,.9fr) minmax(430px,1.1fr);gap:clamp(48px,8vw,110px);align-items:center}
.signal{display:inline-flex;align-items:center;gap:10px;min-height:44px;margin-bottom:16px;
  color:var(--blue);font-size:.88rem;font-weight:700}
.signal svg{width:22px;height:22px}
.hero h1{margin:0;max-width:12ch;font-size:clamp(2.6rem,5.6vw,5.2rem);line-height:1.08;
  letter-spacing:-.05em;font-weight:900}
.hero h1 .soft{display:block;color:var(--blue)}
.lead{max-width:54ch;margin:22px 0 0;color:var(--muted);font-size:clamp(1rem,1.25vw,1.15rem);line-height:2}
.hero-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:30px}
.primary,.secondary{min-height:52px;display:inline-flex;align-items:center;justify-content:center;gap:9px;
  padding:0 22px;text-decoration:none;border:1px solid;border-radius:10px;font-weight:700;
  transition:background-color 150ms ease-out,color 150ms ease-out,border-color 150ms ease-out}
.primary{color:#fff;background:var(--blue);border-color:var(--blue)}
.primary:hover{background:var(--blue-hover);border-color:var(--blue-hover)}
.secondary{color:var(--ink);background:var(--surface);border-color:var(--line-strong)}
.secondary:hover{color:var(--blue-hover);border-color:var(--blue)}
.primary:focus-visible,.secondary:focus-visible,.ftab:focus-visible,.tab:focus-visible{
  outline:3px solid var(--blue-soft);outline-offset:3px}
.watch-wrap{position:relative;padding:24px 0 0 24px}
.watch-wrap::before{content:"";position:absolute;top:0;left:0;width:42%;height:46%;
  border-top:2px solid var(--blue);border-left:2px solid var(--blue);pointer-events:none}
.watch-board{position:relative;background:var(--surface);border:1px solid var(--line-strong);
  border-radius:6px;box-shadow:var(--shadow)}
.board-head{min-height:62px;display:flex;justify-content:space-between;align-items:center;gap:16px;
  padding:0 20px;border-bottom:1px solid var(--line)}
.board-title{display:flex;align-items:center;gap:9px;font-size:.88rem;font-weight:800}
.pulse{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px var(--green-soft)}
.board-time{color:var(--muted);font-size:.76rem}
.listing{min-height:104px;display:grid;grid-template-columns:52px 1fr auto;gap:15px;align-items:center;
  padding:16px 20px;border-bottom:1px solid var(--line)}
.listing:last-of-type{border-bottom:0}
.listing.is-found{background:var(--green-soft)}
.listing-icon{width:48px;height:48px;display:grid;place-items:center;color:var(--blue);
  border:1px solid var(--line);background:var(--surface);border-radius:8px}
.listing-icon svg{width:24px;height:24px}
.listing-copy strong{display:block;font-size:.96rem}
.listing-copy span{display:block;color:var(--muted);font-size:.77rem;margin-top:6px}
.listing-state{text-align:left;color:var(--muted);font-size:.72rem;white-space:nowrap}
.listing-state strong{display:block;color:var(--green);font-size:.81rem}
.meter{width:74px;height:3px;margin-top:8px;background:var(--line);direction:ltr;border-radius:2px}
.meter i{display:block;height:100%;width:var(--meter);background:var(--blue);border-radius:2px}
.board-foot{min-height:50px;display:flex;align-items:center;gap:9px;padding:0 20px;
  color:var(--muted);font-size:.76rem;border-top:1px solid var(--line)}
.board-foot svg{width:17px;height:17px;color:var(--blue)}
.finder-stamp{position:absolute;left:-18px;bottom:54px;width:92px;height:92px;display:grid;place-items:center;
  border:2px solid var(--blue);border-radius:50%;background:var(--paper);color:var(--blue);
  transform:rotate(-11deg);font-size:.71rem;font-weight:800;text-align:center;line-height:1.45}
.coverage{width:min(calc(100% - 48px),var(--max));margin:clamp(48px,7vw,84px) auto 0;display:grid;
  grid-template-columns:1.45fr .55fr;border-top:1px solid var(--line-strong);border-bottom:1px solid var(--line-strong)}
.coverage-main{padding:28px clamp(0px,3vw,36px) 28px 36px;display:flex;align-items:baseline;gap:clamp(18px,4vw,46px)}
.coverage-main strong{font-size:clamp(3.6rem,8vw,7.4rem);line-height:.85;letter-spacing:-.06em}
.coverage-main span{max-width:18ch;color:var(--muted);line-height:1.7}
.coverage-side{border-right:1px solid var(--line);display:grid;grid-template-rows:1fr 1fr}
.metric{padding:20px 26px;display:flex;align-items:baseline;justify-content:space-between;gap:16px}
.metric+.metric{border-top:1px solid var(--line)}
.metric strong{font-size:clamp(1.25rem,2.4vw,2.1rem)}
.metric span{color:var(--muted);font-size:.82rem;text-align:left}
.promo{display:flex;align-items:center;gap:14px;width:min(calc(100% - 48px),var(--max));
  margin:34px auto 0;padding:16px 20px;background:var(--blue-soft);border:1px solid var(--line-strong);
  border-radius:12px;text-decoration:none}
.promo .emj{font-size:26px}
.promo b{font-size:1rem}
.promo .txt{font-size:.82rem;color:var(--muted);display:block;margin-top:3px}
.promo .cta{margin-inline-start:auto;background:var(--blue);color:#fff;font-size:.85rem;font-weight:700;
  padding:10px 22px;border-radius:20px;white-space:nowrap}
.nav{display:flex;gap:8px;overflow-x:auto;padding:16px max(24px,calc(50% - var(--max)/2));
  scrollbar-width:thin}
.nav a{flex:0 0 auto;color:var(--ink);text-decoration:none;font-size:.83rem;font-weight:600;
  border:1px solid var(--line-strong);border-radius:20px;padding:8px 16px;background:var(--surface);
  transition:border-color 150ms ease-out,color 150ms ease-out}
.nav a:hover{border-color:var(--blue);color:var(--blue-hover)}
.sec{width:min(calc(100% - 48px),var(--max));margin:0 auto}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:16px;
  padding:clamp(40px,6vw,72px) 0 6px}
.sec-head h2{margin:0;font-size:clamp(1.7rem,3.4vw,2.9rem);letter-spacing:-.04em;font-weight:900}
.sec-head p{margin:0;color:var(--muted);font-size:.9rem}
.deal-filters{display:flex;gap:8px;flex-wrap:wrap;padding:14px 0 4px}
.ftab{min-height:44px;min-width:72px;padding:8px 18px;border:1px solid var(--line-strong);border-radius:8px;
  color:var(--ink);background:var(--surface);cursor:pointer;font-weight:700;
  transition:background-color 150ms ease-out,color 150ms ease-out,border-color 150ms ease-out}
.ftab:hover{border-color:var(--blue)}
.ftab[aria-selected="true"]{color:#fff;background:var(--blue);border-color:var(--blue)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;padding:18px 0 8px}
.card{position:relative;display:block;background:var(--surface);border:1px solid var(--line);
  border-radius:14px;overflow:hidden;text-decoration:none;color:inherit;
  transition:transform 200ms ease-out,box-shadow 200ms ease-out,border-color 150ms ease-out}
.card:hover{transform:translateY(-3px);box-shadow:var(--shadow);border-color:var(--line-strong)}
.card img{width:100%;height:180px;object-fit:cover;background:var(--blue-soft)}
.card.golden{border-color:var(--gold)}
.badge{position:absolute;top:12px;right:12px;color:#fff;font-size:.74rem;font-weight:800;
  padding:6px 14px;border-radius:20px;background:var(--green)}
.badge.golden{background:var(--gold)}
.num{position:absolute;top:12px;left:12px;background:var(--surface);border:1px solid var(--line-strong);
  color:var(--ink);font-size:.8rem;font-weight:800;min-width:32px;height:32px;line-height:30px;
  text-align:center;border-radius:50%;z-index:2;padding:0 6px}
.body{padding:16px 18px}
.kick{font-size:.78rem;color:var(--muted);margin-bottom:4px}
.card h3{margin:4px 0 8px;font-size:1.28rem;font-weight:800;letter-spacing:-.02em}
.pct{color:var(--blue)}
.title{font-size:.92rem;font-weight:600;margin:0 0 10px;line-height:1.9}
.price{font-size:1.12rem;font-weight:800}
.cmp{margin-top:12px}
.cmpbar{height:8px;background:var(--line);border-radius:5px;overflow:hidden}
.cmpbar i{display:block;height:100%;background:var(--blue);border-radius:5px}
.cmplab{display:flex;justify-content:space-between;font-size:.76rem;color:var(--muted);margin-top:5px}
.cmplab .save{color:var(--green);font-weight:800}
.conf{font-size:.76rem;color:var(--muted);margin-top:10px;border-top:1px dashed var(--line);padding-top:10px}
.empty{text-align:center;color:var(--muted);padding:60px 20px;grid-column:1/-1}
.updated{text-align:center;color:var(--muted);font-size:.8rem;padding:6px 0 4px}
.note{text-align:center;color:var(--muted);font-size:.78rem;padding:8px 20px 8px;max-width:760px;margin:0 auto;line-height:2}
footer{margin-top:56px;border-top:1px solid var(--line);background:var(--surface)}
.foot-inner{width:min(calc(100% - 48px),var(--max));margin:0 auto;padding:26px 0;
  display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;
  color:var(--muted);font-size:.8rem}
.method{width:min(calc(100% - 48px),var(--max));margin:0 auto;padding:clamp(72px,10vw,130px) 0;
  display:grid;grid-template-columns:.8fr 1.2fr;gap:clamp(44px,8vw,110px);align-items:start}
.method-intro{position:sticky;top:42px}
.method-intro h2{margin:0;font-size:clamp(2rem,4vw,3.6rem);line-height:1.15;letter-spacing:-.045em;font-weight:900}
.method-intro p{max-width:44ch;margin:20px 0 0;color:var(--muted);line-height:2}
.steps{border-top:1px solid var(--line-strong)}
.step{display:grid;grid-template-columns:54px 1fr;gap:20px;padding:28px 0;border-bottom:1px solid var(--line)}
.step-num{color:var(--blue);font-size:.86rem;font-weight:800;padding-top:5px}
.step h3{margin:0;font-size:clamp(1.15rem,1.9vw,1.5rem);font-weight:800}
.step p{max-width:58ch;margin:8px 0 0;color:var(--muted);line-height:1.9}
.demo{background:#07152b;color:#f4f8ff;margin-top:clamp(48px,7vw,90px)}
.demo-inner{width:min(calc(100% - 48px),var(--max));margin:0 auto;
  padding:clamp(64px,9vw,110px) 0;display:grid;grid-template-columns:.92fr 1.08fr;
  gap:clamp(44px,8vw,100px);align-items:center}
.demo h2{margin:0;max-width:11ch;font-size:clamp(1.9rem,3.8vw,3.4rem);line-height:1.15;
  letter-spacing:-.045em;font-weight:900}
.demo p{max-width:48ch;margin-top:18px;color:#c0cbe0;line-height:1.95}
.demotabs{display:flex;gap:8px;flex-wrap:wrap;margin-top:26px}
.tab{min-height:44px;min-width:72px;padding:8px 16px;border:1px solid #71819d;border-radius:7px;
  color:#d9e2f1;background:transparent;cursor:pointer;font-weight:700;
  transition:background-color 150ms ease-out,color 150ms ease-out,border-color 150ms ease-out}
.tab:hover{border-color:#d9e2f1}
.tab[aria-selected="true"]{color:#07152b;background:#f4f8ff;border-color:#f4f8ff}
.factor-panel{padding:clamp(22px,3.5vw,36px);border:1px solid #526582;background:#10213c;border-radius:8px}
.factor-head{display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding-bottom:20px;margin-bottom:16px;border-bottom:1px solid #344965}
.factor-head strong{font-size:.9rem}
.factor-head span{color:#aebbd0;font-size:.72rem}
.factor-row{display:grid;grid-template-columns:110px 1fr;align-items:center;gap:14px;margin:16px 0}
.factor-row span{color:#d9e2f1;font-size:.84rem}
.bar{height:6px;background:#293e5d;overflow:hidden;border-radius:3px}
.bar i{display:block;width:var(--w);height:100%;background:#70a7ff;transition:width 250ms ease-in-out}
.panel-caption{margin-top:24px;padding-top:18px;border-top:1px solid #344965;color:#f4f8ff;
  font-size:.92rem;font-weight:700}
.factor-content{transition:opacity 160ms linear,transform 240ms ease-out}
.factor-content.is-exiting{opacity:0;transform:translateY(6px);transition:opacity 170ms linear,transform 170ms ease-in}
@keyframes enter-copy{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@keyframes enter-board{from{opacity:0;transform:translateX(-14px)}to{opacity:1;transform:translateX(0)}}
.hero-copy{animation:enter-copy 260ms ease-out both}
.watch-wrap{animation:enter-board 280ms ease-out 50ms both}
.intro{max-width:800px;margin:0 auto;padding:26px 24px 6px;font-size:.95rem;line-height:2.1;color:var(--muted)}
.intro b{color:var(--ink)}
h2.sec-title{width:min(calc(100% - 48px),var(--max));margin:0 auto;padding:10px 0 0;font-size:1.35rem;font-weight:800}
@media (max-width:900px){
  .hero-inner{grid-template-columns:1fr;gap:52px}
  .watch-wrap{width:min(100%,640px)}
  .coverage{grid-template-columns:1fr}
  .coverage-side{border-right:0;border-top:1px solid var(--line);grid-template-columns:1fr 1fr;grid-template-rows:auto}
  .metric+.metric{border-top:0;border-right:1px solid var(--line)}
  .method{grid-template-columns:1fr}
  .method-intro{position:static}
  .demo-inner{grid-template-columns:1fr}
}
@media (max-width:560px){
  .hero{padding-inline:20px;padding-top:40px}
  .hero-actions{flex-direction:column}
  .primary,.secondary{width:100%}
  .listing{grid-template-columns:44px 1fr;gap:11px;padding:14px}
  .listing-state{grid-column:2;text-align:right;display:flex;align-items:center;gap:10px;white-space:normal}
  .finder-stamp{width:72px;height:72px;left:-8px;bottom:42px;font-size:.62rem}
  .coverage-main{padding:24px 0;gap:22px}
  .coverage-main strong{font-size:4.4rem}
  .coverage-side{grid-template-columns:1fr}
  .metric{padding:16px 0}
  .metric+.metric{border-right:0;border-top:1px solid var(--line)}
  .step{grid-template-columns:36px 1fr;gap:12px}
  .factor-row{grid-template-columns:82px 1fr}
  .foot-inner{flex-direction:column;text-align:center}
}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  *,*::before,*::after{animation-duration:.01ms!important;animation-delay:0ms!important;
    animation-iteration-count:1!important;transition-duration:.01ms!important}
}
</style>"""

def card_html(d: dict, idx: int = 0) -> str:
    t = html.escape(d["title"])
    pct = round(d["discount"] * 100)
    unit = "زیر قیمت محله" if d["category"] in ("house_sell", "house_rent", "commercial_sell", "commercial_rent") else "زیر قیمت بازار"
    badge = ("◇ فرصت طلایی" if d["tier"] == "golden" else "◇ فرصت")
    loc = html.escape(d["district"] or d["city"])
    img = (f'<img src="{html.escape(d["img"])}" loading="lazy" alt="{t}">'
           if d["img"] else "")
    save = d["fair"] - d["price"]
    w = max(4, min(100, round(d["price"] / d["fair"] * 100))) if d["fair"] > 0 else 100
    return f"""
  <a class="card {d['tier']}" href="https://divar.ir/v/{html.escape(d['token'])}" target="_blank" rel="noopener">
    <span class="num">{fa_num(idx + 1)}</span>
    <span class="badge {d['tier']}">{badge}</span>
    {img}
    <div class="body">
    <div class="kick">{loc}</div>
    <h3><span class="pct">{fa_num(pct)}٪</span> {unit}</h3>
    <p class="title">{t}</p>
    <div class="price">{fa_num(f'{d["price"]:,}')} تومان</div>
    <div class="cmp"><div class="cmpbar"><i style="width:{w}%"></i></div>
    <div class="cmplab"><span>منصفانه: {fa_num(f'{d["fair"]:,}')}</span><span class="save">{fa_num(f'{save:,}')} کمتر</span></div></div>
    <div class="conf">{_conf(d['n'])} · مقایسه با {fa_num(d['n'])} آگهی</div>
    </div>
  </a>"""


PROMO_BANNER = """<a class="promo" href="https://t.me/khabarator" target="_blank" rel="noopener">
<span class="emj">🗞️</span>
<span><b>خبراتور</b><span class="txt">ما خبر رو از شایعه جدا می‌کنیم — عضو کانال تلگرام شو</span></span>
<span class="cta">عضویت</span></a>"""

DISCLAIMER = ("درصدهای «زیر قیمت» برآورد ما از قیمت منصفانهٔ هر محله/مدل‌اند و ممکن است "
              "با واقعیت بازار اختلاف داشته باشند؛ قبل از هر تصمیمی، خودتان آگهی و محله را بررسی کنید.")


def nav_html(cities: list[str], cats: list[str]) -> str:
    city_links = "".join(
        f'<a href="{SITE_URL}/city/{city_slug(c)}.html">{html.escape(c)}</a>' for c in cities)
    cat_links = "".join(
        f'<a href="{SITE_URL}/cat/{CATS[c][0]}.html">{html.escape(CATS[c][1])}</a>' for c in cats)
    return f'<nav class="nav" aria-label="دسته‌ها و شهرها"><a href="{SITE_URL}/">همه</a>{cat_links}{city_links}</nav>'


HEAD_COMMON = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f5f6f8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0c111b" media="(prefers-color-scheme: dark)">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700;800;900&display=swap" rel="stylesheet">"""


def topbar_html() -> str:
    return """<header class="topbar"><div class="topbar-inner">
<a class="brand" href="./"><b>قاپ</b></a>
<span class="live"><i></i>فعال — تازه‌سازی هر ۳۰ دقیقه</span>
</div></header>"""


def footer_html() -> str:
    return """<footer><div class="foot-inner">
<span><b>قاپ</b> — زیرقیمت‌های واقعی دیوار</span>
<span>هر ۳۰ دقیقه تازه‌سازی می‌شود</span>
</div></footer>"""


def page_shell(title: str, desc: str, url: str, h1: str, sub: str,
               body: str, nav: str, updated_fa: str) -> str:
    return f"""<!doctype html><html lang="fa" dir="rtl"><head>{HEAD_COMMON}
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{html.escape(url)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
{STYLE}</head><body>
{topbar_html()}
<div class="sec"><div class="sec-head" style="padding-top:34px"><div><h2>{h1}</h2><p>{html.escape(sub)}</p></div></div></div>
{nav}
{body}
<div class="updated">آخرین به‌روزرسانی: {html.escape(updated_fa)}</div>
<p class="note">{html.escape(DISCLAIMER)}</p>
{footer_html()}
</body></html>"""


def build_city_page(city: str, deals: list[dict], nav: str, updated_fa: str) -> str:
    gold = sum(1 for d in deals if d["tier"] == "golden")
    title = f"زیرقیمت‌های دیوار {city} | قاپ"
    desc = (f"آگهی‌های زیر قیمت واقعی دیوار {city} — آپارتمان، خودرو، موبایل و ملک تجاری. "
            f"{fa_num(len(deals))} فرصت فعال ({fa_num(gold)} طلایی)، به‌روزرسانی هر ۳۰ دقیقه.")
    cards = "".join(card_html(d, i) for i, d in enumerate(deals)) or '<div class="empty">هنوز فرصت تازه‌ای ثبت نشده — چند دقیقه دیگر سر بزن.</div>'
    body = (f'<p class="intro">خونه، ماشین، گوشی یا مغازه زیر قیمت در <b>{html.escape(city)}</b> می‌خوای؟ '
            f'این صفحه آگهی‌های دیوار {html.escape(city)} را که از قیمت منصفانهٔ محله/مدل پایین‌ترند، هر ۳۰ دقیقه '
            f'تازه می‌کند. روی هر کارت بزن تا آگهی اصلی در دیوار باز شود.</p>'
            f'<div class="sec"><div class="grid">{cards}</div></div>')
    return page_shell(title, desc, f"{SITE_URL}/city/{city_slug(city)}.html",
                      f"زیرقیمت‌های دیوار {html.escape(city)}",
                      f"{fa_num(len(deals))} فرصت فعال — به‌روزرسانی خودکار هر ۳۰ دقیقه",
                      body, nav, updated_fa)


def build_cat_page(cat: str, deals: list[dict], nav: str, updated_fa: str) -> str:
    slug, fa_name, seo_phrase = CATS[cat]
    title = f"{seo_phrase} در دیوار | قاپ"
    desc = (f"{seo_phrase} — آگهی‌های واقعی دیوار که از قیمت منصفانه پایین‌ترند، در ۳۱ مرکز استان. "
            f"به‌روزرسانی هر ۳۰ دقیقه.")
    cards = "".join(card_html(d, i) for i, d in enumerate(deals)) or '<div class="empty">هنوز فرصت تازه‌ای ثبت نشده — چند دقیقه دیگر سر بزن.</div>'
    body = (f'<p class="intro"><b>{html.escape(fa_name)}</b> زیر قیمت در دیوار؟ این صفحه آگهی‌هایی را نشان می‌دهد '
            f'که از قیمت منصفانهٔ بازار پایین‌ترند — در همهٔ ۳۱ مرکز استان، با تازه‌سازی هر ۳۰ دقیقه.</p>'
            f'<div class="sec"><div class="grid">{cards}</div></div>')
    return page_shell(title, desc, f"{SITE_URL}/cat/{slug}.html",
                      f"{html.escape(seo_phrase)}",
                      f"{fa_num(len(deals))} فرصت فعال در ۳۱ مرکز استان",
                      body, nav, updated_fa)

INDEX_HTML = """<!doctype html><html lang="fa" dir="rtl"><head>__HEAD__
<title>قاپ | زیرقیمت‌های واقعی دیوار در ۳۱ مرکز استان</title>
<meta name="description" content="آگهی‌های زیر قیمت واقعی دیوار — آپارتمان، خودرو، موتورسیکلت، موبایل و ملک تجاری در ۳۱ مرکز استان ایران. به‌روزرسانی خودکار هر ۳۰ دقیقه.">
<meta property="og:title" content="قاپ | زیرقیمت‌های واقعی دیوار">
<meta property="og:description" content="آپارتمان، خودرو، موبایل و ملک تجاری زیر قیمت — ۳۱ مرکز استان، هر ۳۰ دقیقه تازه‌سازی.">
<meta property="og:type" content="website">
""" + STYLE + """</head><body>
<header class="topbar"><div class="topbar-inner">
<a class="brand" href="./"><b>قاپ</b></a>
<span class="live"><i></i>فعال — تازه‌سازی هر ۳۰ دقیقه</span>
</div></header>

<main>
<section class="hero" aria-labelledby="hero-title">
<div class="hero-inner">
<div class="hero-copy">
<div class="signal">
<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="6" stroke="currentColor" stroke-width="2"/><path d="M14.5 14.5L20 20M7 10h6M10 7v6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
رصد هوشمند آگهی‌های دیوار
</div>
<h1 id="hero-title">شکارِ زیرقیمت‌ها، <span class="soft">پیش از بقیه.</span></h1>
<p class="lead">هوش مصنوعی قاپ، فرصت‌های طلایی را شکار می‌کند. موتور هوشمند ما هر ۳۰ دقیقه هزاران آگهی دیوار را می‌خواند، قیمت هر محله و مدل را می‌سنجد و فقط واقعی‌ترین زیرقیمت‌ها را اینجا می‌گذارد.</p>
<div class="hero-actions">
<a class="primary" href="#deals">دیدن فرصت‌های امروز</a>
<a class="secondary" href="#method">قاپ چطور پیدا می‌کند؟</a>
</div>
</div>
<div class="watch-wrap" aria-label="نمایش مفهومی روند سنجش آگهی‌ها">
<div class="watch-board">
<div class="board-head"><div class="board-title"><span class="pulse" aria-hidden="true"></span>صف بررسی قاپ</div><span class="board-time">دور تازهٔ رصد</span></div>
<div class="listing is-found">
<span class="listing-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M4 11.5L12 5l8 6.5V20H4v-8.5zM9.5 20v-5h5v5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg></span>
<span class="listing-copy"><strong>آگهی ملکی</strong><span>مقایسه با بافت همان محله</span></span>
<span class="listing-state"><strong>فرصت شناسایی شد</strong><span class="meter"><i style="--meter:86%"></i></span></span>
</div>
<div class="listing">
<span class="listing-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M5 16l1.2-5.2A2.4 2.4 0 018.5 9h7a2.4 2.4 0 012.3 1.8L19 16M4 16h16v3H4z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="7" cy="18.5" r="1" fill="currentColor"/><circle cx="17" cy="18.5" r="1" fill="currentColor"/></svg></span>
<span class="listing-copy"><strong>آگهی خودرو</strong><span>تطبیق مدل، سال و کارکرد</span></span>
<span class="listing-state">در حال مقایسه<span class="meter"><i style="--meter:61%"></i></span></span>
</div>
<div class="listing">
<span class="listing-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><rect x="6" y="3" width="12" height="18" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M10 17h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></span>
<span class="listing-copy"><strong>کالای دیجیتال</strong><span>سنجش مدل و وضعیت دستگاه</span></span>
<span class="listing-state">در صف بررسی<span class="meter"><i style="--meter:35%"></i></span></span>
</div>
<div class="board-foot"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 7v5l3 2M21 12a9 9 0 11-3-6.7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>هر ۳۰ دقیقه، یک دور بررسی تازه</div>
</div>
<div class="finder-stamp" aria-hidden="true">فقط فرصت<br>واقعی</div>
</div>
</div>
</section>

<section class="coverage" aria-label="پوشش و عملکرد قاپ">
<div class="coverage-main"><strong>۳۱</strong><span>مرکز استان در نقشهٔ رصد قاپ</span></div>
<div class="coverage-side">
<div class="metric"><strong>۳۰ دقیقه</strong><span>فاصلهٔ هر دور بررسی</span></div>
<div class="metric"><strong id="live-count">…</strong><span>آگهی زیرقیمت فعال</span></div>
</div>
</section>

""" + PROMO_BANNER + """
__NAV__

<div class="sec" id="deals">
<div class="sec-head"><div><h2>فرصت‌های امروز</h2><p>روی هر کارت بزن تا آگهی اصلی در دیوار باز شود</p></div></div>
<div class="deal-filters" id="deal-filters" role="tablist" aria-label="فیلتر فرصت‌ها">
<button class="ftab" type="button" role="tab" aria-selected="true" data-f="all">همه</button><button class="ftab" type="button" role="tab" aria-selected="false" data-f="golden">فرصت طلایی</button><button class="ftab" type="button" role="tab" aria-selected="false" data-f="opportunity">فرصت</button>
</div>
<div class="grid" id="grid"></div>
<div class="updated" id="updated"></div>
</div>

<section class="method" id="method" aria-labelledby="method-title">
<div class="method-intro"><h2 id="method-title">قیمت پایین کافی نیست.</h2><p>قاپ تفاوت میان «ارزان به‌نظر رسیدن» و «فرصت واقعی» را با مقایسه آگهی‌های مشابه پیدا می‌کند.</p></div>
<div class="steps">
<article class="step"><div class="step-num">۰۱</div><div><h3>خواندن بازار</h3><p>آگهی‌های تازه دیوار در شهرهای تحت پوشش، دوره‌ای بررسی می‌شوند.</p></div></article>
<article class="step"><div class="step-num">۰۲</div><div><h3>مقایسه درست با درست</h3><p>قیمت هر آگهی با محله، مدل و نمونه‌های مشابه خودش سنجیده می‌شود.</p></div></article>
<article class="step"><div class="step-num">۰۳</div><div><h3>جداکردن فرصت</h3><p>فقط آگهی‌هایی که اختلاف معناداری با بازار دارند، به‌عنوان زیرقیمت دیده می‌شوند.</p></div></article>
</div>
</section>

<section class="demo" aria-labelledby="demo-title">
<div class="demo-inner">
<div>
<h2 id="demo-title">هر دسته، معیار خودش را دارد.</h2>
<p>نوع مقایسه را عوض کن تا ببینی قاپ برای هر بازار به چه نشانه‌هایی نگاه می‌کند.</p>
<div class="demotabs" role="tablist" aria-label="انتخاب دسته آگهی">
<button class="tab" type="button" role="tab" aria-selected="true" data-kind="home">ملک</button>
<button class="tab" type="button" role="tab" aria-selected="false" data-kind="car">خودرو</button>
<button class="tab" type="button" role="tab" aria-selected="false" data-kind="digital">دیجیتال</button>
</div>
</div>
<div class="factor-panel" aria-live="polite">
<div class="factor-head"><strong>وزن معیارهای مقایسه</strong><span>نمای مفهومی</span></div>
<div class="factor-content">
<div class="factor-row"><span id="factor-a">محله</span><div class="bar"><i style="--w:92%"></i></div></div>
<div class="factor-row"><span id="factor-b">متراژ</span><div class="bar"><i style="--w:78%"></i></div></div>
<div class="factor-row"><span id="factor-c">سن بنا</span><div class="bar"><i style="--w:61%"></i></div></div>
<div class="panel-caption" id="panel-caption">سنجش در بافت همان محله، نه میانگین کل شهر</div>
</div>
</div>
</div>
</section>

</main>
<p class="note">__DISCLAIMER__</p>
<footer><div class="foot-inner">
<span><b>قاپ</b> — زیرقیمت‌های واقعی دیوار</span>
<span>هر ۳۰ دقیقه تازه‌سازی می‌شود</span>
</div></footer>
<script>
const FA="۰۱۲۳۴۵۶۷۸۹", fa=n=>String(n).replace(/\\d/g,d=>FA[d]);
let all=[],f="all";
async function load(){
  try{
    const r=await fetch("deals.json"); const j=await r.json(); all=j.deals||[];
    document.getElementById("updated").textContent="آخرین به‌روزرسانی: "+j.updated_fa+" — "+fa(j.count)+" آگهی زیرقیمت";
    const lc=document.getElementById("live-count"); if(lc&&j.count!=null) lc.textContent=fa(j.count);
  }catch(e){ all=[]; }
  render();
}
function conf(n){return n>=50?"اطمینان بالا":n>=15?"اطمینان متوسط":"اطمینان کم";}
function unit(cat){return ["house_sell","house_rent","commercial_sell","commercial_rent"].includes(cat)?"زیر قیمت محله":"زیر قیمت بازار";}
function cardHTML(d,i){
  const pct=Math.round(d.discount*100), save=d.fair-d.price;
  const w=Math.max(4,Math.min(100,Math.round(d.price/d.fair*100)));
  return '<a class="card '+d.tier+'" href="https://divar.ir/v/'+d.token+'" target="_blank" rel="noopener">'
  +'<span class="num">'+fa(i+1)+'</span>'
  +'<span class="badge '+d.tier+'">'+(d.tier==="golden"?"◇ فرصت طلایی":"◇ فرصت")+'</span>'
  +(d.img?'<img src="'+d.img+'" loading="lazy" alt="">':"")
  +'<div class="body"><div class="kick">'+(d.district||d.city||"")+'</div>'
  +'<h3><span class="pct">'+fa(pct)+'٪</span> '+unit(d.category)+'</h3>'
  +'<p class="title" data-i="'+i+'"></p>'
  +'<div class="price">'+fa(d.price.toLocaleString("en"))+' تومان</div>'
  +'<div class="cmp"><div class="cmpbar"><i style="width:'+w+'%"></i></div>'
  +'<div class="cmplab"><span>منصفانه: '+fa(d.fair.toLocaleString("en"))+'</span><span class="save">'+fa(save.toLocaleString("en"))+' کمتر</span></div></div>'
  +'<div class="conf">'+conf(d.n||0)+' · مقایسه با '+fa(d.n||0)+' آگهی</div>'
  +'</div></a>';
}
function render(){
  const g=document.getElementById("grid");
  const list=all.filter(d=>f==="all"?true:d.tier===f);
  if(!list.length){g.innerHTML='<div class="empty">هنوز فرصت تازه‌ای ثبت نشده — چند دقیقه دیگر سر بزن.</div>';return;}
  g.innerHTML=list.map(cardHTML).join("");
  g.querySelectorAll(".title").forEach(el=>{el.textContent=list[+el.dataset.i].title;});
}
document.querySelectorAll("#deal-filters .ftab").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll("#deal-filters .ftab").forEach(x=>x.setAttribute("aria-selected","false"));
  b.setAttribute("aria-selected","true"); f=b.dataset.f; render();
}));
load();
(function(){
  var content={
    home:{factors:["محله","متراژ","سن بنا"],widths:[92,78,61],caption:"سنجش در بافت همان محله، نه میانگین کل شهر"},
    car:{factors:["مدل","کارکرد","سال ساخت"],widths:[88,73,67],caption:"مقایسه با خودروهای هم‌مدل و هم‌سال"},
    digital:{factors:["مدل","وضعیت","حافظه"],widths:[94,69,58],caption:"مقایسه میان نسخه‌ها و شرایط نزدیک به هم"}
  };
  var tabs=Array.prototype.slice.call(document.querySelectorAll(".demotabs .tab"));
  var labels=[document.getElementById("factor-a"),document.getElementById("factor-b"),document.getElementById("factor-c")];
  var bars=Array.prototype.slice.call(document.querySelectorAll(".bar i"));
  var caption=document.getElementById("panel-caption");
  var factorContent=document.querySelector(".factor-content");
  var reduced=window.matchMedia("(prefers-reduced-motion: reduce)");
  var timer=null;
  function applyItem(tab){
    var item=content[tab.getAttribute("data-kind")];
    tabs.forEach(function(t){t.setAttribute("aria-selected",String(t===tab));});
    labels.forEach(function(label,i){label.textContent=item.factors[i];});
    bars.forEach(function(bar,i){bar.style.setProperty("--w",item.widths[i]+"%");});
    caption.textContent=item.caption;
  }
  tabs.forEach(function(tab){
    tab.addEventListener("click",function(){
      if(tab.getAttribute("aria-selected")==="true")return;
      if(timer)window.clearTimeout(timer);
      if(reduced.matches){applyItem(tab);return;}
      factorContent.classList.add("is-exiting");
      timer=window.setTimeout(function(){applyItem(tab);factorContent.classList.remove("is-exiting");},170);
    });
  });
})();
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
    index = INDEX_HTML.replace("__HEAD__", HEAD_COMMON).replace("__NAV__", nav).replace("__DISCLAIMER__", html.escape(DISCLAIMER))
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

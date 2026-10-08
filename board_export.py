#!/usr/bin/env python3
"""board_export.py — static-site generator for Shekar Forsat (قاپ) v3.

Redesign v3 port: elevated design system (hero + radar console, live board
with rich cards, anatomy, method, closing), Persian RTL, dark/light aware.
Cards are <a> links to divar.ir, server-rendered per page + JS hydration
on the homepage from deals.json.
"""
import json, math, os, re, sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "db.sqlite3")
OUT = os.path.join(ROOT, "site")

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
    "house_sell": "آپارتمان فروشی", "house_rent": "آپارتمان اجاره",
    "car": "خودرو", "motorcycle": "موتورسیکلت",
    "mobile": "موبایل", "commercial_sell": "مغازه فروشی",
    "commercial_rent": "مغازه اجاره",
}

CAT_ICON = {"house_sell": "home", "house_rent": "home", "commercial_sell": "home",
            "commercial_rent": "home", "car": "car", "motorcycle": "car", "mobile": "digital"}

ICON_SVG = {
    "home": ('<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 11.5L12 5l8 6.5V20H4v-8.5zM9.5 20v-5h5v5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>'),
    "car": ('<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 16l1.2-5.2A2.4 2.4 0 018.5 9h7a2.4 2.4 0 012.3 1.8L19 16M4 16h16v3H4z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="7" cy="18.5" r="1" fill="currentColor"/><circle cx="17" cy="18.5" r="1" fill="currentColor"/></svg>'),
    "digital": ('<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="6" y="3" width="12" height="18" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M10 17h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'),
}

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(n):
    return f"{n:,}".translate(FA_DIGITS)


def load_deals(limit=400):
    import sqlite3
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id,title,city,category,price,fair_price,pct_below_fair,divar_token,n_comps,inserted_at"
        " FROM deals ORDER BY pct_below_fair DESC, inserted_at DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _conf(n):
    if n is None:
        return "نامشخص"
    return "بالا" if n >= 50 else ("خوب" if n >= 15 else "پایه")


def card_html(d):
    price, fair = d["price"], d["fair_price"]
    pct = round(d["pct_below_fair"] * 100)
    w = max(4, min(100, round(price / fair * 100))) if fair else 100
    tier = "golden" if d["pct_below_fair"] >= 0.25 else "opportunity"
    badge = ('<span class="gold-badge">فرصت طلایی</span>' if tier == "golden"
             else '<span class="deal-badge">فرصت</span>')
    icon = ICON_SVG.get(CAT_ICON.get(d["category"], "home"), ICON_SVG["home"])
    n = d.get("n_comps")
    return (
        f'<a class="opportunity" data-tier="{tier}" href="https://divar.ir/v/{d["divar_token"]}"'
        f' target="_blank" rel="noopener" aria-label="{d["title"]}، {fa_num(pct)} درصد زیر قیمت">'
        f'<div class="card-top"><span class="category-icon" aria-hidden="true">{icon}</span>{badge}</div>'
        f'<h3>{d["title"]}</h3><span class="location">{d["city"]}</span>'
        f'<div class="price"><small>قیمت آگهی</small><strong>{fa_num(price)} تومان</strong></div>'
        f'<div class="fair-row"><span>فاصله تا قیمت منصفانه</span><strong>{fa_num(pct)}٪ پایین‌تر</strong></div>'
        f'<div class="compare"><i style="--deal:{w}%"></i></div>'
        f'<div class="fair-value"><span>آگهی: {fa_num(price)}</span><span>منصفانه: {fa_num(fair)}</span></div>'
        f'<div class="card-analysis"><div class="analysis-grid">'
        f'<div><span>نمونه‌های همتا</span><strong>{fa_num(n) if n is not None else "—"} آگهی</strong></div>'
        f'<div><span>اطمینان تحلیل</span><strong>{_conf(n)}</strong></div>'
        f'<div><span>دسته‌بندی</span><strong>{CATS.get(d["category"], "")}</strong></div>'
        f'</div></div></a>'
    )

STYLE = """
    :root {
      color-scheme: light dark;
      --paper: #f1f3f6;
      --paper-2: #e9edf2;
      --surface: #ffffff;
      --surface-raised: #ffffff;
      --ink: #07162c;
      --muted: #586578;
      --soft: #7c8797;
      --line: #cfd6df;
      --line-strong: #aab5c3;
      --accent: #0066ee;
      --accent-strong: #0055c9;
      --accent-soft: #e3efff;
      --green: #087552;
      --green-soft: #e4f7ef;
      --gold: #9c6400;
      --gold-soft: #fff2ce;
      --navy: #06142a;
      --navy-2: #0c203f;
      --navy-line: #29415f;
      --white: #f7faff;
      --max: 1240px;
      --shadow: 0 26px 70px rgba(17, 37, 67, .15), 0 5px 18px rgba(17, 37, 67, .08);
      --shadow-hover: 0 38px 86px rgba(13, 36, 72, .21), 0 10px 30px rgba(13, 36, 72, .11);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --paper: #080c13;
        --paper-2: #0c121c;
        --surface: #111925;
        --surface-raised: #141e2d;
        --ink: #f2f6fc;
        --muted: #aeb9c9;
        --soft: #8795a8;
        --line: #2c394b;
        --line-strong: #506079;
        --accent: #6ba7ff;
        --accent-strong: #98c2ff;
        --accent-soft: #152d50;
        --green: #71ddb5;
        --green-soft: #10372b;
        --gold: #ffd36f;
        --gold-soft: #3f3010;
        --navy: #030914;
        --navy-2: #0a1a33;
        --navy-line: #2d4565;
        --white: #f5f8fd;
        --shadow: 0 30px 72px rgba(0, 0, 0, .45), 0 5px 20px rgba(0, 0, 0, .24);
        --shadow-hover: 0 42px 92px rgba(0, 0, 0, .58), 0 12px 32px rgba(0, 0, 0, .30);
      }
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      min-width: 320px;
      overflow-x: hidden;
      background: var(--paper);
      color: var(--ink);
      font-family: "Vazirmatn", Tahoma, sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    button, a { font: inherit; }
    a { color: inherit; }
    ::selection { background: var(--accent); color: #fff; }

    .hero {
      position: relative;
      isolation: isolate;
      overflow: hidden;
      min-height: min(960px, 100svh);
      padding: clamp(52px, 7vw, 90px) max(24px, env(safe-area-inset-right)) clamp(76px, 9vw, 116px) max(24px, env(safe-area-inset-left));
      border-bottom: 1px solid var(--line);
      background:
        radial-gradient(circle at 15% 20%, color-mix(in srgb, var(--accent) 12%, transparent), transparent 32%),
        var(--paper);
    }
    .hero::before {
      content: "";
      position: absolute;
      inset: 0;
      z-index: -1;
      pointer-events: none;
      opacity: .38;
      background-image: linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px);
      background-size: 88px 88px;
      mask-image: linear-gradient(to bottom, #000, transparent 72%);
    }
    .hero-inner {
      width: min(100%, var(--max));
      margin: 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1.04fr) minmax(460px, .96fr);
      gap: clamp(52px, 7vw, 104px);
      align-items: center;
    }
    .signal {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-height: 42px;
      margin-bottom: clamp(18px, 3vw, 28px);
      color: var(--accent);
      font-size: .85rem;
      font-weight: 800;
    }
    .signal i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 5px var(--accent-soft); }
    h1 {
      margin: 0;
      max-width: 8.2ch;
      font-size: clamp(4.4rem, 9vw, 9.3rem);
      line-height: .91;
      letter-spacing: -.082em;
      font-weight: 900;
    }
    h1 .outline {
      display: block;
      color: transparent;
      -webkit-text-stroke: 2px var(--accent);
      text-stroke: 2px var(--accent);
    }
    .lead {
      max-width: 570px;
      margin: clamp(30px, 4vw, 44px) 0 0;
      color: var(--muted);
      font-size: clamp(1rem, 1.35vw, 1.2rem);
      line-height: 2;
    }
    .hero-actions { display: flex; flex-wrap: wrap; gap: 11px; margin-top: 32px; }
    .primary, .secondary {
      min-height: 54px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      padding: 0 22px;
      border: 1px solid;
      border-radius: 11px;
      text-decoration: none;
      font-weight: 750;
      transition: transform 180ms ease-out, box-shadow 180ms ease-out, background-color 150ms ease-out, border-color 150ms ease-out, color 150ms ease-out;
    }
    .primary { background: #0066ee; border-color: #0066ee; color: #fff; box-shadow: 0 10px 28px rgba(0, 102, 238, .24); }
    .primary:hover { transform: translateY(-2px); background: #0055c9; border-color: #0055c9; box-shadow: 0 16px 34px rgba(0, 102, 238, .31); }
    .secondary { background: var(--surface); border-color: var(--line); color: var(--ink); }
    .secondary:hover { transform: translateY(-2px); border-color: var(--accent); color: var(--accent); }
    .primary:focus-visible, .secondary:focus-visible, .filter:focus-visible, .opportunity:focus-visible { outline: 3px solid color-mix(in srgb, var(--accent) 38%, transparent); outline-offset: 4px; }
    .arrow { width: 18px; height: 18px; }

    .hero-console { position: relative; min-width: 0; padding: 28px 0 0 28px; }
    .hero-console::before {
      content: "";
      position: absolute;
      inset: 0 auto auto 0;
      width: 44%;
      height: 45%;
      border-top: 2px solid var(--accent);
      border-left: 2px solid var(--accent);
    }
    .console {
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line-strong);
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .console-head { min-height: 68px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 22px; border-bottom: 1px solid var(--line); }
    .console-title { display: flex; align-items: center; gap: 10px; font-size: .86rem; font-weight: 850; }
    .console-title i { width: 9px; height: 9px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 5px var(--green-soft); animation: breathe 2.4s ease-in-out infinite; }
    .console-head span { color: var(--soft); font-size: .73rem; }
    .radar { position: relative; height: 318px; overflow: hidden; background: var(--navy); color: var(--white); }
    .radar-grid { position: absolute; inset: 0; opacity: .42; background-image: linear-gradient(var(--navy-line) 1px, transparent 1px), linear-gradient(90deg, var(--navy-line) 1px, transparent 1px); background-size: 54px 54px; }
    .radar::after { content: ""; position: absolute; width: 42%; height: 140%; top: -20%; left: 42%; transform-origin: 50% 50%; background: linear-gradient(90deg, transparent, rgba(73, 147, 255, .22)); clip-path: polygon(0 50%, 100% 0, 100% 100%); animation: sweep 4.8s linear infinite; }
    .deal-ping { position: absolute; z-index: 2; display: grid; place-items: center; width: 14px; height: 14px; border: 2px solid #8abbff; border-radius: 50%; background: #0b2a55; }
    .deal-ping::after { content: ""; position: absolute; inset: -9px; border: 1px solid #6aa6ff; border-radius: 50%; animation: ping 2s ease-out infinite; }
    .p1 { top: 25%; right: 25%; }
    .p2 { top: 63%; right: 56%; animation-delay: .7s; }
    .p3 { top: 40%; right: 75%; animation-delay: 1.4s; }
    .console-stat { position: absolute; z-index: 3; min-width: 155px; padding: 16px 18px; border: 1px solid #405a7c; background: rgba(7, 22, 45, .92); }
    .console-stat small { display: block; color: #9cabc0; font-size: .69rem; }
    .console-stat strong { display: block; margin-top: 4px; font-size: 1.55rem; }
    .s1 { top: 28px; right: 24px; }
    .s2 { bottom: 26px; left: 24px; }
    .trend { display: flex; align-items: flex-end; gap: 4px; height: 26px; margin-top: 8px; direction: ltr; }
    .trend i { width: 8px; height: var(--h); background: #69a6ff; }
    .console-bottom { min-height: 84px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 22px; }
    .latest { min-width: 0; }
    .latest small { display: block; color: var(--muted); font-size: .72rem; }
    .latest strong { display: block; margin-top: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .latest-badge { flex: none; padding: 8px 11px; background: var(--gold-soft); color: var(--gold); border-radius: 999px; font-size: .72rem; font-weight: 800; }
    .console-ticket { position: absolute; right: -22px; bottom: 94px; z-index: 5; width: 106px; height: 106px; display: grid; place-items: center; border: 2px solid var(--accent); border-radius: 50%; background: var(--paper); color: var(--accent); transform: rotate(8deg); text-align: center; line-height: 1.45; font-size: .72rem; font-weight: 900; }

    .numbers { width: min(calc(100% - 48px), var(--max)); margin: 0 auto; display: grid; grid-template-columns: 1.15fr .85fr 1fr; border-bottom: 1px solid var(--line-strong); }
    .number { min-height: 184px; padding: 32px clamp(20px, 3vw, 38px); display: flex; flex-direction: column; justify-content: center; }
    .number + .number { border-right: 1px solid var(--line); }
    .number strong { font-size: clamp(2.4rem, 4.5vw, 4.8rem); line-height: 1; letter-spacing: -.05em; }
    .number span { margin-top: 13px; color: var(--muted); font-size: .84rem; }

    .board-section { padding: clamp(106px, 13vw, 174px) 24px; }
    .section-head { width: min(100%, var(--max)); margin: 0 auto clamp(42px, 6vw, 70px); display: grid; grid-template-columns: 1fr .7fr; gap: 50px; align-items: end; }
    h2 { margin: 0; font-size: clamp(2.7rem, 5.8vw, 6.2rem); line-height: 1.02; letter-spacing: -.065em; }
    .section-copy { max-width: 48ch; justify-self: end; color: var(--muted); line-height: 2; }
    .eyebrow { display: block; margin-bottom: 15px; color: var(--accent); font-size: .8rem; font-weight: 850; }
    .board-shell { width: min(100%, var(--max)); margin: 0 auto; border: 1px solid var(--line-strong); background: var(--surface); box-shadow: var(--shadow); }
    .board-toolbar { min-height: 78px; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 16px 20px; border-bottom: 1px solid var(--line); }
    .toolbar-title { display: flex; align-items: center; gap: 10px; font-size: .84rem; font-weight: 800; }
    .toolbar-title i { width: 8px; height: 8px; background: var(--green); border-radius: 50%; box-shadow: 0 0 0 4px var(--green-soft); }
    .toolbar-title small { color: var(--soft); font-weight: 500; }
    .filters { display: flex; flex-wrap: wrap; gap: 7px; }
    .filter { min-height: 39px; padding: 7px 15px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: var(--muted); cursor: pointer; transition: color 150ms ease-out, background-color 150ms ease-out, border-color 150ms ease-out; }
    .filter:hover { border-color: var(--accent); color: var(--accent); }
    .filter[aria-pressed="true"] { background: var(--ink); border-color: var(--ink); color: var(--paper); }
    .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--line); }
    .cards.is-filtered { display: block; padding: 28px; background: var(--paper-2); }
    .cards.is-filtered .opportunity:not([hidden]) { display: block; width: min(100%, 490px); margin: 0 auto; box-shadow: var(--shadow); }
    .opportunity {
      position: relative;
      min-width: 0;
      padding: clamp(24px, 3vw, 34px);
      border: 0;
      background: var(--surface);
      color: var(--ink);
      text-align: right;
      cursor: pointer;
      transition: transform 220ms ease-out, box-shadow 220ms ease-out, background-color 150ms ease-out;
    }
    .opportunity:hover { z-index: 2; transform: translateY(-8px); background: var(--surface-raised); box-shadow: var(--shadow-hover); }
    .opportunity[hidden] { display: none; }
    .card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
    .category-icon { width: 54px; height: 54px; display: grid; place-items: center; color: var(--accent); border: 1px solid var(--line); background: var(--paper); }
    .category-icon svg { width: 27px; height: 27px; }
    .gold-badge, .deal-badge { padding: 7px 10px; border-radius: 999px; font-size: .68rem; font-weight: 850; white-space: nowrap; }
    .gold-badge { color: var(--gold); background: var(--gold-soft); }
    .deal-badge { color: var(--green); background: var(--green-soft); }
    .opportunity h3 { margin: 29px 0 0; font-size: clamp(1.15rem, 1.6vw, 1.42rem); line-height: 1.6; }
    .location { display: block; margin-top: 6px; color: var(--soft); font-size: .78rem; }
    .price { margin-top: 27px; padding-top: 23px; border-top: 1px solid var(--line); }
    .price small { display: block; color: var(--muted); font-size: .72rem; }
    .price strong { display: block; margin-top: 3px; font-size: clamp(1.55rem, 2.5vw, 2.25rem); letter-spacing: -.04em; }
    .fair-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: 20px; color: var(--muted); font-size: .74rem; }
    .fair-row strong { color: var(--green); font-size: .86rem; }
    .compare { position: relative; height: 8px; margin-top: 10px; background: var(--paper-2); overflow: hidden; }
    .compare i { display: block; width: var(--deal); height: 100%; background: var(--accent); transition: width 500ms cubic-bezier(.22, 1, .36, 1); }
    .compare::after { content: ""; position: absolute; left: 7px; top: -3px; bottom: -3px; width: 2px; background: var(--ink); }
    .fair-value { margin-top: 9px; display: flex; justify-content: space-between; color: var(--soft); font-size: .68rem; }
    .card-more { margin-top: 25px; display: flex; align-items: center; justify-content: space-between; color: var(--accent); font-size: .76rem; font-weight: 800; }
    .card-more svg { width: 18px; height: 18px; transition: transform 180ms ease-out; }
    .opportunity:hover .card-more svg { transform: translateX(-4px); }
    .opportunity.is-open .card-more svg { transform: rotate(-90deg); }
    .card-analysis { max-height: 0; overflow: hidden; opacity: 0; border-top: 0 solid var(--line); transition: max-height 320ms cubic-bezier(.22, 1, .36, 1), opacity 180ms ease-out, margin-top 320ms ease-out, padding-top 320ms ease-out, border-width 320ms ease-out; }
    .opportunity.is-open .card-analysis { max-height: 150px; margin-top: 22px; padding-top: 18px; border-top-width: 1px; opacity: 1; }
    .analysis-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .analysis-grid span { display: block; color: var(--soft); font-size: .65rem; }
    .analysis-grid strong { display: block; margin-top: 4px; color: var(--ink); font-size: .79rem; }
    .sample-note { min-height: 52px; display: flex; align-items: center; gap: 9px; padding: 0 20px; border-top: 1px solid var(--line); color: var(--soft); font-size: .72rem; }
    .sample-note svg { width: 16px; height: 16px; color: var(--accent); }

    .anatomy { overflow: hidden; background: var(--navy); color: var(--white); }
    .anatomy-inner { width: min(calc(100% - 48px), var(--max)); margin: 0 auto; padding: clamp(92px, 12vw, 148px) 0; display: grid; grid-template-columns: .86fr 1.14fr; gap: clamp(60px, 9vw, 130px); align-items: center; }
    .anatomy h2 { max-width: 9ch; }
    .anatomy-copy p { max-width: 47ch; margin: 26px 0 0; color: #b9c6da; line-height: 2; }
    .stack { position: relative; min-height: 460px; }
    .layer { position: absolute; right: 0; width: 100%; min-height: 112px; padding: 25px 28px; border: 1px solid var(--navy-line); background: var(--navy-2); box-shadow: 0 20px 50px rgba(0, 0, 0, .18); transition: transform 250ms ease-out, border-color 250ms ease-out; }
    .layer:hover { border-color: #6ea9ff; transform: translateX(-10px); }
    .layer:nth-child(1) { top: 0; right: 0; z-index: 3; }
    .layer:nth-child(2) { top: 125px; right: 7%; z-index: 2; }
    .layer:nth-child(3) { top: 250px; right: 14%; z-index: 1; }
    .layer-num { color: #70a8ff; font-size: .76rem; font-weight: 850; }
    .layer strong { display: block; margin-top: 7px; font-size: 1.12rem; }
    .layer span { display: block; margin-top: 6px; color: #9fb0c8; font-size: .76rem; }

    .method { width: min(calc(100% - 48px), var(--max)); margin: 0 auto; padding: clamp(108px, 14vw, 174px) 0; display: grid; grid-template-columns: .74fr 1.26fr; gap: clamp(58px, 10vw, 145px); align-items: start; }
    .method-intro { position: sticky; top: 38px; }
    .method-intro h2 { max-width: 8.8ch; }
    .method-intro p { max-width: 43ch; margin: 24px 0 0; color: var(--muted); line-height: 2; }
    .steps { counter-reset: steps; border-top: 1px solid var(--line-strong); }
    .step { counter-increment: steps; display: grid; grid-template-columns: 64px 1fr; gap: 20px; padding: 34px 0; border-bottom: 1px solid var(--line); }
    .step::before { content: "0" counter(steps); color: var(--accent); font-weight: 850; padding-top: 4px; }
    .step h3 { margin: 0; font-size: clamp(1.2rem, 2vw, 1.62rem); }
    .step p { max-width: 56ch; margin: 10px 0 0; color: var(--muted); line-height: 1.95; }

    .closing { border-top: 1px solid var(--line); }
    .closing-inner { width: min(calc(100% - 48px), var(--max)); margin: 0 auto; padding: clamp(92px, 13vw, 154px) 0; display: grid; grid-template-columns: 1fr auto; gap: 60px; align-items: end; }
    .closing h2 { max-width: 12ch; }
    .closing p { max-width: 50ch; margin: 22px 0 0; color: var(--muted); line-height: 2; }
    .closing-mark { width: clamp(116px, 14vw, 172px); aspect-ratio: 1; position: relative; border: 1px solid var(--line-strong); border-radius: 50%; }
    .closing-mark::before { content: ""; position: absolute; inset: 25%; border: 6px solid var(--accent); border-radius: 50%; }
    .closing-mark::after { content: ""; position: absolute; width: 42%; height: 8px; left: 4%; bottom: 16%; background: var(--accent); transform: rotate(-45deg); transform-origin: center; }

    @keyframes breathe { 0%,100% { box-shadow: 0 0 0 4px var(--green-soft); } 50% { box-shadow: 0 0 0 8px var(--green-soft); } }
    @keyframes sweep { to { transform: rotate(360deg); } }
    @keyframes ping { from { opacity: 1; transform: scale(.65); } to { opacity: 0; transform: scale(1.55); } }
    @keyframes enter { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
    .hero-copy { animation: enter 420ms ease-out both; }
    .hero-console { animation: enter 480ms ease-out 90ms both; }

    @media (max-width: 980px) {
      .hero { min-height: auto; }
      .hero-inner { grid-template-columns: 1fr; }
      .hero-copy { max-width: 780px; }
      .hero-console { width: min(100%, 680px); }
      .section-head { grid-template-columns: 1fr; }
      .section-copy { justify-self: start; }
      .cards { grid-template-columns: 1fr 1fr; }
      .opportunity:last-child { grid-column: 1 / -1; }
      .anatomy-inner { grid-template-columns: 1fr; }
      .stack { width: min(100%, 700px); }
      .method { grid-template-columns: 1fr; }
      .method-intro { position: static; }
    }
    @media (max-width: 680px) {
      .hero { padding-inline: 20px; padding-top: 42px; }
      h1 { font-size: clamp(4rem, 21vw, 6.6rem); }
      h1 .outline { -webkit-text-stroke-width: 1.5px; }
      .hero-actions { flex-direction: column; }
      .primary, .secondary { width: 100%; }
      .hero-console { padding: 14px 0 0 12px; }
      .radar { height: 285px; }
      .console-stat { min-width: 136px; padding: 13px; }
      .console-ticket { width: 78px; height: 78px; right: -8px; bottom: 82px; font-size: .61rem; }
      .console-bottom { align-items: flex-start; min-height: 106px; }
      .latest strong { white-space: normal; line-height: 1.65; }
      .numbers { width: calc(100% - 40px); grid-template-columns: 1fr; }
      .number { min-height: 130px; padding: 25px 0; }
      .number + .number { border-right: 0; border-top: 1px solid var(--line); }
      .board-section { padding-inline: 20px; }
      .board-toolbar { align-items: flex-start; flex-direction: column; padding: 18px; }
      .cards { grid-template-columns: 1fr; }
      .cards.is-filtered { padding: 14px; }
      .opportunity:last-child { grid-column: auto; }
      .opportunity:hover { transform: none; }
      .anatomy-inner, .method, .closing-inner { width: calc(100% - 40px); }
      .stack { min-height: 445px; }
      .layer { width: 96%; padding: 22px; }
      .layer:nth-child(2) { right: 4%; }
      .layer:nth-child(3) { right: 8%; }
      .step { grid-template-columns: 42px 1fr; gap: 12px; }
      .closing-inner { grid-template-columns: 1fr; }
      .closing-mark { display: none; }
    }
    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
      *, *::before, *::after { animation-duration: .01ms !important; animation-delay: 0ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; }
    }
  
    /* --- live-site additions (v3 port) --- */
    a.opportunity { text-decoration: none; display: block; }
    a.opportunity:hover { transform: translateY(-4px); }
    .topbar {
      position: sticky; top: 0; z-index: 50;
      display: flex; align-items: center; gap: 14px;
      padding: 12px max(24px, env(safe-area-inset-right)) 12px max(24px, env(safe-area-inset-left));
      background: color-mix(in srgb, var(--paper) 88%, transparent);
      backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--line);
    }
    .brand { font-weight: 900; font-size: 1.15rem; color: var(--ink); text-decoration: none; }
    .brand small { display: block; font-size: .68rem; font-weight: 600; color: var(--soft); }
    .nav { overflow-x: auto; scrollbar-width: none; -webkit-overflow-scrolling: touch; }
    .nav::-webkit-scrollbar { display: none; }
    .nav-row { display: flex; gap: 8px; width: max-content; padding: 2px; }
    .chip {
      display: inline-flex; align-items: center; min-height: 44px;
      padding: 0 16px; border: 1px solid var(--line); border-radius: 999px;
      background: var(--surface); color: var(--muted); font-size: .82rem; font-weight: 700;
      text-decoration: none; white-space: nowrap;
    }
    .chip.on { background: var(--ink); border-color: var(--ink); color: var(--paper); }
    .promo {
      width: min(100%, var(--max)); margin: clamp(48px, 6vw, 80px) auto 0;
      padding: 0 max(24px, env(safe-area-inset-right)) 0 max(24px, env(safe-area-inset-left));
    }
    .promo-box {
      display: flex; align-items: center; justify-content: space-between; gap: 18px; flex-wrap: wrap;
      padding: clamp(22px, 3vw, 34px) clamp(24px, 4vw, 44px);
      border: 1px solid var(--navy-line); border-radius: 22px;
      background: linear-gradient(135deg, var(--navy), var(--navy-2));
      color: var(--white); box-shadow: var(--shadow);
    }
    .promo-box strong { font-size: 1.15rem; font-weight: 800; }
    .promo-box p { margin: 6px 0 0; color: color-mix(in srgb, var(--white) 72%, transparent); font-size: .92rem; }
    .promo-box a {
      min-height: 48px; display: inline-flex; align-items: center; padding: 0 26px;
      border-radius: 999px; background: var(--white); color: var(--navy);
      font-weight: 800; text-decoration: none; font-size: .92rem;
    }
    .updated { font-size: .8rem; color: var(--soft); }
    .foot {
      width: min(100%, var(--max)); margin: clamp(56px, 7vw, 90px) auto 0;
      padding: 28px max(24px, env(safe-area-inset-right)) 44px max(24px, env(safe-area-inset-left));
      border-top: 1px solid var(--line); color: var(--soft); font-size: .82rem;
      display: flex; flex-wrap: wrap; gap: 10px 28px; align-items: center; justify-content: space-between;
    }
    .intro { color: var(--muted); font-size: .95rem; max-width: 62ch; }
    .empty {
      padding: 60px 20px; text-align: center; color: var(--soft);
      border: 1px dashed var(--line-strong); border-radius: 18px; background: var(--surface);
    }
    .page-head { width: min(100%, var(--max)); margin: 0 auto; padding: clamp(36px, 5vw, 60px) max(24px, env(safe-area-inset-right)) 8px max(24px, env(safe-area-inset-left)); }
    .page-head h1 { margin: 0 0 10px; font-size: clamp(1.8rem, 4vw, 2.6rem); font-weight: 900; letter-spacing: -.02em; }
    .page-head .eyebrow { margin-bottom: 12px; display: inline-block; }
    @media (max-width: 760px) { .cards { grid-template-columns: 1fr; } }
"""


def nav_html(active_city=None, active_cat=None):
    city_chips = ['<a class="chip%s" href="%s">%s</a>' % (
        " on" if active_city == c else "",
        ("index.html" if c == "tehran" else f"city-{CITY_SLUG[c]}.html") if c != active_city else "#",
        "تهران" if c == "tehran" else c) for c in
        ["تهران", "آذربایجان شرقی", "اصفهان", "فارس", "خراسان رضوی", "خوزستان", "گیلان", "مازندران"]]
    cat_chips = ['<a class="chip%s" href="%s">%s</a>' % (
        " on" if active_cat == k else "",
        ("index.html" if k is None else f"cat-{k}.html"),
        ("همه" if k is None else CATS[k])) for k in [None] + list(CATS)]
    return ('<nav class="nav" aria-label="ناوبری"><div class="nav-row">'
            + "".join(city_chips) + "".join(cat_chips) + "</div></nav>")


FOOT = ('<footer class="foot"><span>قاپ — موتور شکار فرصت‌های زیرقیمت</span>'
        '<span class="updated" id="updated"></span></footer>')


INDEX_HTML = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<meta name="color-scheme" content="light dark"/>
<meta name="theme-color" content="#f1f3f6" media="(prefers-color-scheme: light)"/>
<meta name="theme-color" content="#080c13" media="(prefers-color-scheme: dark)"/>
<link rel="icon" href="data:,"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800;900&display=swap" rel="stylesheet"/>
<title>قاپ | شکار فرصت‌های زیرقیمت</title>
<meta name="description" content="قاپ آگهی‌های دیوار را با قیمت منصفانه بازار مقایسه می‌کند و فرصت‌های واقعی زیرقیمت را نشان می‌دهد."/>
<style>{STYLE}</style>
</head>
<body>
<main>
<section class="hero">
  <div class="hero-inner">
    <div class="hero-copy">
      <div class="signal"><i aria-hidden="true"></i>موتور شکار فرصت‌های زیرقیمت</div>
      <h1>قبل از بازار، <span class="outline">پیدایش کن.</span></h1>
      <p class="lead">قاپ هزاران آگهی را با نبض واقعی هر محله، مدل و دسته مقایسه می‌کند؛ تا فرصتی را ببینی که بقیه هنوز از کنارش رد می‌شوند.</p>
      <div class="hero-actions">
        <a class="primary" href="#live-board">دیدن برد فرصت‌ها
          <svg class="arrow" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 10l5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </a>
        <a class="secondary" href="#method">منطق قاپ چطور کار می‌کند؟</a>
      </div>
    </div>
    <div class="hero-console" aria-label="نمایش موتور رصد قاپ">
      <div class="console">
        <div class="console-head"><div class="console-title"><i aria-hidden="true"></i>رادار قاپ</div><span>یک دور کامل رصد</span></div>
        <div class="radar">
          <div class="radar-grid"></div>
          <span class="deal-ping p1"></span><span class="deal-ping p2"></span><span class="deal-ping p3"></span>
          <div class="console-stat s1"><small>شهرهای تحت پوشش</small><strong>۳۱ مرکز</strong><div class="trend"><i style="--h:30%"></i><i style="--h:45%"></i><i style="--h:38%"></i><i style="--h:65%"></i><i style="--h:72%"></i><i style="--h:88%"></i></div></div>
          <div class="console-stat s2"><small>معیارهای هم‌زمان</small><strong>۱۲۸+</strong><div class="trend"><i style="--h:38%"></i><i style="--h:65%"></i><i style="--h:50%"></i><i style="--h:78%"></i><i style="--h:92%"></i><i style="--h:76%"></i></div></div>
        </div>
        <div class="console-bottom"><div class="latest"><small>نمونهٔ تازه‌ترین شکار</small><strong id="latest-hunt">…</strong></div><span class="latest-badge">فرصت طلایی</span></div>
      </div>
      <div class="console-ticket" aria-hidden="true">هوش بازار<br/>در یک نگاه</div>
    </div>
  </div>
</section>

<section class="numbers" aria-label="پوشش قاپ">
  <div class="number"><strong>۳۱</strong><span>مرکز استان در نقشه رصد</span></div>
  <div class="number"><strong>۳۰ دقیقه</strong><span>فاصلهٔ هر دور بررسی</span></div>
  <div class="number"><strong id="live-count">…</strong><span>آگهی زیرقیمت فعال</span></div>
</section>

{NAV}

<section class="board-section" id="live-board" aria-labelledby="board-title">
  <div class="section-head">
    <div><span class="eyebrow">محصول زنده</span><h2 id="board-title">برد زندهٔ فرصت‌ها.</h2></div>
    <p class="section-copy">قیمت آگهی کنار برآورد منصفانهٔ بازار قرار می‌گیرد؛ نه یک برچسب مبهم، بلکه اختلافی که با چشم می‌بینی.</p>
  </div>
  <div class="board-shell">
    <div class="board-toolbar">
      <div class="toolbar-title"><i aria-hidden="true"></i>فرصت‌های امروز</div>
      <div class="filters" aria-label="فیلتر فرصت‌ها">
        <button class="filter" type="button" data-tier="all" aria-pressed="true">همه</button>
        <button class="filter" type="button" data-tier="golden" aria-pressed="false">فرصت طلایی</button>
        <button class="filter" type="button" data-tier="opportunity" aria-pressed="false">فرصت</button>
      </div>
    </div>
    <div class="cards" id="grid" aria-live="polite"></div>
  </div>
</section>

<div class="promo"><div class="promo-box">
  <div><strong>خبرهای مهم را هم از دست نده</strong><p>کانال تلگرامی خبراتور — گزیدهٔ مهم‌ترین خبرهای ایران و جهان</p></div>
  <a href="https://t.me/khabarator" target="_blank" rel="noopener">عضویت در خبراتور</a>
</div></div>

<section class="anatomy" aria-labelledby="anatomy-title">
  <div class="anatomy-inner">
    <div class="anatomy-copy"><span class="eyebrow">زیر پوست هر نتیجه</span><h2 id="anatomy-title">یک قیمت. سه لایه فهم.</h2><p>قاپ فقط عددها را مرتب نمی‌کند. زمینهٔ آگهی را می‌فهمد، همتاهای درست را پیدا می‌کند و فاصلهٔ معنادار را از ارزان‌نمایی جدا می‌سازد.</p></div>
    <div class="stack" aria-label="سه لایه تحلیل قاپ">
      <div class="layer"><span class="layer-num">۰۱</span><strong>زمینهٔ آگهی</strong><span>محله، مدل، سال، وضعیت و ویژگی‌های اثرگذار</span></div>
      <div class="layer"><span class="layer-num">۰۲</span><strong>بازار همتا</strong><span>مقایسه فقط با نمونه‌های واقعاً نزدیک و قابل قیاس</span></div>
      <div class="layer"><span class="layer-num">۰۳</span><strong>امتیاز فرصت</strong><span>فاصلهٔ قیمت، کیفیت آگهی و احتمال ارزش خرید</span></div>
    </div>
  </div>
</section>

<section class="method" id="method" aria-labelledby="method-title">
  <div class="method-intro"><span class="eyebrow">منطق شکار</span><h2 id="method-title">قیمت پایین، کافی نیست.</h2><p>فرصت واقعی وقتی شکل می‌گیرد که قیمت، مشخصات و بازار همتا یک داستان واحد بگویند.</p></div>
  <div class="steps">
    <article class="step"><div><h3>خواندن پیوستهٔ بازار</h3><p>آگهی‌های تازه در شهرهای تحت پوشش، دوره‌ای وارد چرخهٔ مقایسه می‌شوند.</p></div></article>
    <article class="step"><div><h3>مقایسهٔ درست با درست</h3><p>هر مورد با محله، مدل و نمونه‌های نزدیک به خودش سنجیده می‌شود؛ نه با یک میانگین گمراه‌کننده.</p></div></article>
    <article class="step"><div><h3>رتبه‌بندی اختلاف معنادار</h3><p>فقط فاصله‌هایی که از فیلتر کیفیت و همسانی عبور کنند، روی برد فرصت‌ها بالا می‌آیند.</p></div></article>
  </div>
</section>

<section class="closing">
  <div class="closing-inner"><div><h2>بازار شلوغ است. دید تو نباید باشد.</h2><p>قاپ هزاران آگهی را به چند تصمیم روشن تبدیل می‌کند؛ با مقایسه‌ای که می‌توانی ببینی، بفهمی و روی آن حساب باز کنی.</p></div><div class="closing-mark" aria-hidden="true"></div></div>
</section>
</main>
{FOOT}
<script>
const ICONS = {ICONS_JS};
const CATS = {CATS_JS};
const faD = s => String(s).replace(/\\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[d]);
const faN = n => faD(Number(n).toLocaleString("en-US"));
const conf = n => n == null ? "نامشخص" : n >= 50 ? "بالا" : n >= 15 ? "خوب" : "پایه";
function card(d){
  const pct = Math.round(d.pct_below_fair*100);
  const w = d.fair_price ? Math.max(4, Math.min(100, Math.round(d.price/d.fair_price*100))) : 100;
  const golden = d.pct_below_fair >= 0.25;
  const badge = golden ? '<span class="gold-badge">فرصت طلایی</span>' : '<span class="deal-badge">فرصت</span>';
  const icon = {"home":ICONS.home,"car":ICONS.car,"digital":ICONS.digital}[d.icon||"home"];
  return '<a class="opportunity" data-tier="'+(golden?"golden":"opportunity")+'" href="https://divar.ir/v/'+d.divar_token+'" target="_blank" rel="noopener" aria-label="'+d.title+'، '+faN(pct)+' درصد زیر قیمت">'
    +'<div class="card-top"><span class="category-icon" aria-hidden="true">'+icon+'</span>'+badge+'</div>'
    +'<h3>'+d.title+'</h3><span class="location">'+d.city+'</span>'
    +'<div class="price"><small>قیمت آگهی</small><strong>'+faN(d.price)+' تومان</strong></div>'
    +'<div class="fair-row"><span>فاصله تا قیمت منصفانه</span><strong>'+faN(pct)+'٪ پایین‌تر</strong></div>'
    +'<div class="compare"><i style="--deal:'+w+'%"></i></div>'
    +'<div class="fair-value"><span>آگهی: '+faN(d.price)+'</span><span>منصفانه: '+faN(d.fair_price)+'</span></div>'
    +'<div class="card-analysis"><div class="analysis-grid">'
    +'<div><span>نمونه‌های همتا</span><strong>'+(d.n_comps==null?"—":faN(d.n_comps))+' آگهی</strong></div>'
    +'<div><span>اطمینان تحلیل</span><strong>'+conf(d.n_comps)+'</strong></div>'
    +'<div><span>دسته‌بندی</span><strong>'+(CATS[d.category]||"")+'</strong></div>'
    +'</div></div></a>';
}
let ALL = [];
fetch("deals.json").then(r=>r.json()).then(ds=>{
  ALL = ds;
  document.getElementById("grid").innerHTML = ds.slice(0,60).map(card).join("") || '<div class="empty">فعلاً آگهی زیرقیمتی ثبت نشده.</div>';
  document.getElementById("live-count").textContent = faN(ds.length);
  const g = ds.find(d=>d.pct_below_fair>=0.25) || ds[0];
  if (g) document.getElementById("latest-hunt").textContent = g.title + " · " + faN(Math.round(g.pct_below_fair*100)) + "٪ زیر قیمت";
  const u = document.getElementById("updated");
  if (u && ds._ts) u.textContent = "به‌روزرسانی: " + ds._ts;
});
document.querySelectorAll(".filter").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll(".filter").forEach(x=>x.setAttribute("aria-pressed","false"));
  b.setAttribute("aria-pressed","true");
  const t = b.dataset.tier;
  const list = t==="all" ? ALL : ALL.filter(d => (d.pct_below_fair>=0.25?"golden":"opportunity")===t);
  document.getElementById("grid").innerHTML = list.slice(0,60).map(card).join("") || '<div class="empty">موردی در این گروه نیست.</div>';
}));
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
<link rel="icon" href="data:,"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800;900&display=swap" rel="stylesheet"/>
<style>{STYLE}</style>
</head>
<body>
<header class="topbar"><a class="brand" href="index.html">قاپ<small>شکار فرصت‌های زیرقیمت</small></a>{NAV}</header>
<main>
<div class="page-head"><span class="eyebrow">{EYEBROW}</span><h1>{H1}</h1><p class="intro">{INTRO}</p></div>
<section class="board-section"><div class="board-shell"><div class="cards">{CARDS}</div></div></section>
</main>
{FOOT}
</body>
</html>
"""


def build():
    deals = load_deals()
    os.makedirs(OUT, exist_ok=True)
    now = datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M")
    icons_js = json.dumps({k: v for k, v in ICON_SVG.items()})
    cats_js = json.dumps(CATS)
    enriched = []
    for d in deals:
        e = dict(d)
        e["icon"] = CAT_ICON.get(d["category"], "home")
        enriched.append(e)
    with open(os.path.join(OUT, "deals.json"), "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False)
    nav = nav_html()
    idx = INDEX_HTML.replace("{STYLE}", STYLE).replace("{NAV}", nav).replace("{FOOT}", FOOT)
    idx = idx.replace("{ICONS_JS}", icons_js).replace("{CATS_JS}", cats_js)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(idx)

    for city, slug in CITY_SLUG.items():
        ds = [d for d in deals if d["city"] == city][:60]
        cards = "".join(card_html(d) for d in ds) or '<div class="empty">فعلاً آگهی زیرقیمتی در این شهر ثبت نشده.</div>'
        pg = PAGE_HTML.replace("{TITLE}", f"فرصت‌های {city}").replace("{STYLE}", STYLE)
        pg = pg.replace("{NAV}", nav_html(active_city=city)).replace("{FOOT}", FOOT)
        pg = pg.replace("{EYEBROW}", "فرصت‌های شهری").replace("{H1}", f"فرصت‌های زیرقیمت {city}")
        pg = pg.replace("{INTRO}", f"{len(ds)} آگهی زیرقیمت در {city} — با مقایسه قیمت آگهی و برآورد منصفانه بازار.")
        pg = pg.replace("{CARDS}", cards)
        with open(os.path.join(OUT, f"city-{slug}.html"), "w", encoding="utf-8") as f:
            f.write(pg)

    for ck, cn in CATS.items():
        ds = [d for d in deals if d["category"] == ck][:60]
        cards = "".join(card_html(d) for d in ds) or '<div class="empty">فعلاً آگهی زیرقیمتی در این دسته ثبت نشده.</div>'
        pg = PAGE_HTML.replace("{TITLE}", cn).replace("{STYLE}", STYLE)
        pg = pg.replace("{NAV}", nav_html(active_cat=ck)).replace("{FOOT}", FOOT)
        pg = pg.replace("{EYEBROW}", "فرصت‌های دسته‌بندی").replace("{H1}", f"فرصت‌های {cn}")
        pg = pg.replace("{INTRO}", f"{len(ds)} آگهی زیرقیمت در دسته {cn}.")
        pg = pg.replace("{CARDS}", cards)
        with open(os.path.join(OUT, f"cat-{ck}.html"), "w", encoding="utf-8") as f:
            f.write(pg)

    urls = ["https://shekarforsat.github.io/shekar-forsat/"]
    for slug in CITY_SLUG.values():
        urls.append(f"https://shekarforsat.github.io/shekar-forsat/city-{slug}.html")
    for ck in CATS:
        urls.append(f"https://shekarforsat.github.io/shekar-forsat/cat-{ck}.html")
    sm = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>")
    with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sm)
    with open(os.path.join(OUT, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nAllow: /\nSitemap: https://shekarforsat.github.io/shekar-forsat/sitemap.xml\n")
    print(f"built {len(deals)} deals -> {OUT} at {now}")


if __name__ == "__main__":
    build()

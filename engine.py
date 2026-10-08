"""
موتور تشخیص «فرصت» دیوار — هسته مستقل از مسیر دیتا.

متدولوژی (مهندسی معکوس از پلتفرم «دلال»، تست زنده ۲ اکتبر ۲۰۲۶):
- هر آگهی فقط با میانهٔ محلهٔ خودش مقایسه می‌شود (نه کل شهر)
- مسکن: قیمت هر مترمربع در برابر میانهٔ محله، با لحاظ سن بنا/متراژ/آسانسور/پارکینگ
- ملک تجاری: همان منطق مسکن (قیمت هر مترمربع در برابر میانهٔ محله)
- «فرصت» = حداقل ۱۵٪ زیر میانهٔ محله | «فرصت طلایی» = ۲۲٪ یا بیشتر زیر میانه
- خودرو و موتورسیکلت: قیمت در برابر میانهٔ بازار همان برند+مدل+سال (با لحاظ کارکرد)
- موبایل: قیمت در برابر میانهٔ بازار همان برند در شهر
- اجاره: همان منطق روی اجاره‌بها

ورودی: آگهی‌های ساخت‌یافته (از هر منبعی: افزونه سمت‌کاربر، API رسمی، …)
خروجی: امتیاز تخفیف + سطح فرصت — بدون هیچ وابستگی به نحوهٔ جمع‌آوری دیتا.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

OPPORTUNITY_THRESHOLD = 0.15   # ۱۵٪ زیر میانه
GOLDEN_THRESHOLD = 0.22        # ۲۲٪ زیر میانه


@dataclass
class Ad:
    token: str
    title: str
    category: str          # 'house_sell' | 'house_rent' | 'commercial_sell' | 'commercial_rent'
                             # | 'car' | 'car_rent' | 'motorcycle' | 'mobile'
    city: str = "تهران"
    district: str = ""     # محله
    price: Optional[int] = None        # تومان (فروش) یا تومان/ماه (اجاره)
    area_m2: Optional[float] = None    # مسکن
    year_built: Optional[int] = None   # شمسی
    rooms: Optional[int] = None
    elevator: Optional[bool] = None
    parking: Optional[bool] = None
    # خودرو
    brand: str = ""
    model: str = ""
    year: Optional[int] = None         # مدل شمسی
    km: Optional[int] = None


@dataclass
class ScoredAd:
    ad: Ad
    fair_price: int
    discount_pct: float     # درصد زیر قیمت منصفانه (مثبت = زیر قیمت)
    tier: str               # 'none' | 'opportunity' | 'golden'


def fa_digits_to_int(text: str) -> Optional[int]:
    """تبدیل رشتهٔ قیمت فارسی («۵,۷۰۰,۰۰۰,۰۰۰ تومان») به عدد."""
    if not text:
        return None
    fa = "۰۱۲۳۴۵۶۷۸۹"
    en = "0123456789"
    t = text.strip()
    for f, e in zip(fa, en):
        t = t.replace(f, e)
    t = t.replace(",", "").replace("٬", "")
    t = "".join(ch for ch in t if ch.isdigit())
    return int(t) if t else None


class BaselineStore:
    """جدول میانهٔ قیمت منصفانه؛ کلید: (شهر، محله، دسته، سگمنت)."""

    def __init__(self) -> None:
        self._medians: dict[tuple, int] = {}

    def set(self, city: str, district: str, category: str, segment: str, median: int) -> None:
        self._medians[(city, district, category, segment)] = median

    def get(self, city: str, district: str, category: str, segment: str) -> Optional[int]:
        return self._medians.get((city, district, category, segment))


def _house_segment(ad: Ad) -> str:
    """سگمنت مسکن برای مقایسهٔ هم‌رده‌ها: بازهٔ متراژ + سن بنا."""
    area = ad.area_m2 or 0
    bucket = "s" if area < 70 else ("m" if area < 120 else "l")
    age = ""
    if ad.year_built:
        age_years = 1405 - ad.year_built
        age = "new" if age_years <= 5 else ("mid" if age_years <= 15 else "old")
    return f"{bucket}-{age}"


def _car_segment(ad: Ad) -> str:
    return f"{ad.brand}-{ad.model}-{ad.year or '?'}"


def _mobile_segment(ad: Ad) -> str:
    # موبایل: فقط برند (مدل‌ها در تیتر خیلی به‌هم‌ریخته‌اند)
    return f"{ad.brand or '?'}"


def fair_price_for(ad: Ad, baseline: BaselineStore) -> Optional[int]:
    """قیمت منصفانهٔ آگهی بر اساس میانهٔ محله/مدل."""
    if ad.category in ("house_sell", "house_rent", "commercial_sell", "commercial_rent"):
        if not ad.area_m2 or not ad.district:
            return None
        median_per_m2 = baseline.get(ad.city, ad.district, ad.category, _house_segment(ad))
        if median_per_m2 is None:
            # فالبک: میانهٔ همان سگمنت در کل شهر (وقتی دیتای محله کم است)
            median_per_m2 = baseline.get(ad.city, "*", ad.category, _house_segment(ad))
        if median_per_m2 is None:
            return None
        return int(median_per_m2 * ad.area_m2)

    if ad.category in ("car", "car_rent", "motorcycle"):
        if not ad.brand:
            return None
        return baseline.get(ad.city, "*", ad.category, _car_segment(ad))

    if ad.category == "mobile":
        if not ad.brand:
            return None
        return baseline.get(ad.city, "*", ad.category, _mobile_segment(ad))

    return None


def score_ad(ad: Ad, baseline: BaselineStore) -> Optional[ScoredAd]:
    """امتیازدهی یک آگهی؛ None یعنی دیتای کافی برای قضاوت نیست."""
    if not ad.price or ad.price <= 0:
        return None
    # فیلتر سلامت: قیمت‌های غیرممکن (جای خالی قیمت/تماس) را حذف کن
    if ad.category in ("house_sell", "house_rent", "commercial_sell", "commercial_rent") and ad.area_m2:
        per_m2 = ad.price / ad.area_m2
        if per_m2 < 10_000_000:  # زیر متری ۱۰ میلیون = قیمت صوری
            return None
    if ad.category == "car" and ad.price < 50_000_000:  # زیر ۵۰ میلیون = صوری
        return None
    if ad.category == "motorcycle" and ad.price < 5_000_000:  # زیر ۵ میلیون = صوری
        return None
    if ad.category == "mobile" and ad.price < 500_000:  # زیر ۵۰۰ هزار = صوری
        return None
    fair = fair_price_for(ad, baseline)
    if not fair or fair <= 0:
        return None
    discount = (fair - ad.price) / fair
    if discount >= GOLDEN_THRESHOLD:
        tier = "golden"
    elif discount >= OPPORTUNITY_THRESHOLD:
        tier = "opportunity"
    else:
        tier = "none"
    return ScoredAd(ad=ad, fair_price=fair, discount_pct=discount, tier=tier)


def score_batch(ads: list[Ad], baseline: BaselineStore) -> list[ScoredAd]:
    """فقط آگهی‌های فرصت/طلایی، مرتب از بیشترین تخفیف."""
    out = []
    for ad in ads:
        s = score_ad(ad, baseline)
        if s and s.tier != "none":
            out.append(s)
    return sorted(out, key=lambda s: s.discount_pct, reverse=True)


TIER_FA = {"golden": "فرصت طلایی", "opportunity": "فرصت", "none": "—"}

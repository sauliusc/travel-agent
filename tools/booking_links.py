"""Booking.com search links built by code, with the trip's dates and group.

The Accommodation agent ends its plan with a machine-readable block of the
recommended place per stay (city, name, check-in/out, price). From it, code
builds a Booking.com search URL that opens on the right property name, dates
and number of people -- it works even when the agent found no exact property
link -- and checks the traveller's price limit.
"""

import datetime as dt
import json
import re
from urllib.parse import urlencode

_PICKS = re.compile(r"```(?:json)?\s*(\{\s*\"picks\".*?\})\s*```", re.S)

PICKS_RULE = (
    "End your answer with exactly one fenced ```json block of the form "
    '{"picks": [{"city": "...", "name": "...", "checkin": "YYYY-MM-DD", '
    '"checkout": "YYYY-MM-DD", "price_per_night_eur": 85}]} -- one entry per stay '
    "(consecutive nights in the same place), the option you recommend first, with the exact "
    "property name; price_per_night_eur null if you found no price. It is read by code."
)


def picks(accommodation: str) -> list[dict]:
    """The recommended stays from the plan's picks block ([] if absent or invalid)."""
    m = _PICKS.search(accommodation or "")
    if not m:
        return []
    try:
        items = json.loads(m.group(1)).get("picks", [])
    except ValueError:
        return []
    out = []
    for p in items:
        try:
            checkin = dt.date.fromisoformat(str(p["checkin"]))
            checkout = dt.date.fromisoformat(str(p["checkout"]))
        except (KeyError, ValueError):
            continue
        if checkout <= checkin or not p.get("city"):
            continue
        price = p.get("price_per_night_eur")
        out.append({"city": str(p["city"]), "name": str(p.get("name") or "").strip() or None,
                    "checkin": checkin, "checkout": checkout,
                    "price_per_night_eur": price if isinstance(price, (int, float)) else None})
    return out


def search_url(city: str, name: str | None, checkin: dt.date, checkout: dt.date,
               adults: int, rooms: int = 1) -> str:
    return "https://www.booking.com/searchresults.html?" + urlencode({
        "ss": f"{name}, {city}" if name else city,
        "checkin": checkin.isoformat(), "checkout": checkout.isoformat(),
        "group_adults": adults, "group_children": 0, "no_rooms": rooms,
    })


def search_links(accommodation: str, travelers: int) -> list[dict]:
    """Per stay: city, name, dates, nights, price and the Booking.com search URL."""
    return [{
        "city": p["city"], "name": p["name"],
        "checkin": p["checkin"].isoformat(), "checkout": p["checkout"].isoformat(),
        "nights": (p["checkout"] - p["checkin"]).days,
        "price_per_night_eur": p["price_per_night_eur"],
        "url": search_url(p["city"], p["name"], p["checkin"], p["checkout"], travelers),
    } for p in picks(accommodation)]


def over_budget(accommodation: str, max_price: int | None) -> list[str]:
    """Picks priced above the traveller's per-night limit."""
    if not max_price:
        return []
    return [f"{p['name'] or p['city']} ({p['city']}): {p['price_per_night_eur']} €/naktį > {max_price} €"
            for p in picks(accommodation)
            if p["price_per_night_eur"] is not None and p["price_per_night_eur"] > max_price]


def strip_picks(accommodation: str) -> str:
    """The plan without the machine-readable block (for traveller-facing use)."""
    return _PICKS.sub("", accommodation or "").rstrip()

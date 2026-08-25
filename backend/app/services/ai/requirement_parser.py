"""A. AI Campaign Requirement Parser.

Extracts structured requirements from a natural-language description using
keyword/pattern matching against the vocabulary that actually exists in the
database (real city names, real category names) — never invents a city or
category the app doesn't know about. This is intentionally simple pattern
matching, not an LLM call (none is configured in this project); every field
is traceable back to the exact phrase that produced it.
"""
from __future__ import annotations

import re

KNOWN_CITIES = [
    "Mumbai", "Pune", "Nashik", "Thane", "Navi Mumbai", "Bangalore", "Delhi",
    "Gurgaon", "Hyderabad", "Chennai", "Ahmedabad", "Kolkata", "Jaipur",
    "Indore", "Nagpur",
]
KNOWN_CATEGORIES = [
    "Retail", "Fashion", "Electronics", "Grocery", "Food & Beverage", "Banking",
    "Automotive", "Hospitality", "Telecom", "Healthcare", "Beauty", "E-commerce",
    "Footwear", "Apparel",
]
CATEGORY_SYNONYMS = {
    "food": "Food & Beverage", "beverage": "Food & Beverage", "cafe": "Food & Beverage",
    "ecommerce": "E-commerce", "e-commerce": "E-commerce",
}


def parse_requirements(text: str) -> dict:
    if not text or not text.strip():
        return {"raw_text": text or "", "parsed_fields": {}, "matched_phrases": []}

    lower = text.lower()
    matched: list[str] = []
    fields: dict = {}

    # required_shoppers: "5 shoppers", "need 3 members"
    m = re.search(r"\b(\d{1,3})\s+shopper", lower)
    if m:
        fields["required_shoppers"] = int(m.group(1))
        matched.append(m.group(0))

    # location: first known city literally present in the text
    for city in KNOWN_CITIES:
        if city.lower() in lower:
            fields["location"] = city
            matched.append(city)
            break

    # categories: every known category (or synonym) mentioned
    found_categories: list[str] = []
    for cat in KNOWN_CATEGORIES:
        if cat.lower() in lower and cat not in found_categories:
            found_categories.append(cat)
            matched.append(cat)
    for syn, cat in CATEGORY_SYNONYMS.items():
        if syn in lower and cat not in found_categories:
            found_categories.append(cat)
            matched.append(syn)
    if found_categories:
        fields["categories"] = found_categories

    # minimum_rating: "rating above 4", "rating of at least 4.5"
    m = re.search(r"rating\s*(?:above|over|of at least|at least|>\s*=?)?\s*(\d(?:\.\d)?)", lower)
    if m:
        fields["minimum_rating"] = float(m.group(1))
        matched.append(m.group(0))

    # maximum_distance_km: "within 15 km", "15km"
    m = re.search(r"(?:within\s+)?(\d{1,3})\s*km", lower)
    if m:
        fields["maximum_distance_km"] = int(m.group(1))
        matched.append(m.group(0))

    # minimum_completion_rate: "completion rate above 80%"
    m = re.search(r"completion\s*(?:rate)?\s*(?:above|over|at least)?\s*(\d{1,3})\s*%", lower)
    if m:
        fields["minimum_completion_rate"] = min(1.0, int(m.group(1)) / 100)
        matched.append(m.group(0))

    fields["availability_required"] = "availab" in lower
    fields["experience_required"] = "experience" in lower

    return {"raw_text": text, "parsed_fields": fields, "matched_phrases": matched}

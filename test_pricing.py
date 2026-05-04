"""
Quick logic test for the pricing engine.
Creates 10 fake car listings and verifies deal scoring works end-to-end.
"""
import sys
sys.path.insert(0, "/sessions/wonderful-jolly-franklin/mnt/outputs/car-deal-finder")

from scraper.processors.pricing_engine import process_listings

listings = [
    # --- Toyota Camry 2020, mileage band 40k ---
    {"make": "Toyota", "model": "Camry", "year": 2020, "mileage_km": 42000, "price_sar": 85000, "url": "http://example.com/1"},  # market reference
    {"make": "Toyota", "model": "Camry", "year": 2020, "mileage_km": 44000, "price_sar": 87000, "url": "http://example.com/2"},  # market reference
    {"make": "Toyota", "model": "Camry", "year": 2020, "mileage_km": 41000, "price_sar": 63000, "url": "http://example.com/3"},  # excellent deal (~26% below median)
    {"make": "Toyota", "model": "Camry", "year": 2020, "mileage_km": 43000, "price_sar": 75000, "url": "http://example.com/4"},  # good deal (~12% below median)
    {"make": "Toyota", "model": "Camry", "year": 2020, "mileage_km": 45000, "price_sar": 95000, "url": "http://example.com/5"},  # overpriced

    # --- Hyundai Sonata 2019, mileage band 60k ---
    {"make": "Hyundai", "model": "Sonata", "year": 2019, "mileage_km": 62000, "price_sar": 55000, "url": "http://example.com/6"},  # market reference
    {"make": "Hyundai", "model": "Sonata", "year": 2019, "mileage_km": 63000, "price_sar": 57000, "url": "http://example.com/7"},  # market reference
    {"make": "Hyundai", "model": "Sonata", "year": 2019, "mileage_km": 61000, "price_sar": 48000, "url": "http://example.com/8"},  # good deal (~14% below median)
    {"make": "Hyundai", "model": "Sonata", "year": 2019, "mileage_km": 64000, "price_sar": 53000, "url": "http://example.com/9"},  # fair deal

    # --- Missing price (unscored) ---
    {"make": "Kia", "model": "Optima", "year": 2021, "mileage_km": 30000, "price_sar": None, "url": "http://example.com/10"},
]

results = process_listings(listings)

print(f"\n{'='*75}")
print(f"{'URL':<32} {'Make/Model/Year':<25} {'Price SAR':>10} {'Score':>7} {'Tier':<12}")
print(f"{'='*75}")
for r in results:
    url_short = r["url"].replace("http://example.com/", "#")
    car_label = f"{r.get('make','-')} {r.get('model','-')} {r.get('year','-')}"
    price = f"{r.get('price_sar', 'N/A'):>10}" if r.get("price_sar") else f"{'N/A':>10}"
    score = f"{r['deal_score']:>+7.2f}%" if r["deal_score"] is not None else f"{'N/A':>8}"
    tier = r["deal_tier"]
    print(f"{url_short:<32} {car_label:<25} {price} {score} {tier}")

print(f"{'='*75}\n")

# --- Assertions ---
scored = {r["url"]: r for r in results}

assert scored["http://example.com/3"]["deal_tier"] == "excellent", \
    f"Listing #3 should be 'excellent', got: {scored['http://example.com/3']['deal_tier']}"

assert scored["http://example.com/4"]["deal_tier"] == "good", \
    f"Listing #4 should be 'good', got: {scored['http://example.com/4']['deal_tier']}"

assert scored["http://example.com/5"]["deal_tier"] == "overpriced", \
    f"Listing #5 should be 'overpriced', got: {scored['http://example.com/5']['deal_tier']}"

assert scored["http://example.com/8"]["deal_tier"] == "good", \
    f"Listing #8 should be 'good', got: {scored['http://example.com/8']['deal_tier']}"

assert scored["http://example.com/10"]["deal_tier"] == "unscored", \
    f"Listing #10 should be 'unscored', got: {scored['http://example.com/10']['deal_tier']}"

# Verify sorted order: best deal_score first, unscored last
scored_only = [r for r in results if r["deal_score"] is not None]
for i in range(len(scored_only) - 1):
    assert scored_only[i]["deal_score"] >= scored_only[i+1]["deal_score"], \
        f"Sort order broken at index {i}: {scored_only[i]['deal_score']} < {scored_only[i+1]['deal_score']}"

unscored_positions = [i for i, r in enumerate(results) if r["deal_tier"] == "unscored"]
assert all(pos == len(results) - 1 for pos in unscored_positions), \
    "Unscored listings should be at the end"

print("All assertions passed! Pricing engine logic is correct.")

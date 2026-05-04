# Used Car Deal Finder — Saudi Arabia

An automated system that scrapes used car listings from **haraj.com**, **syarah.com**, and **motory.com**, scores each listing against current market prices, and exposes the results via a REST API.

---

## How It Works

1. GitHub Actions scrapes all three sites every 4 hours.
2. The pricing engine groups comparable cars (same make, model, year, mileage band) and computes the median market price.
3. Each listing is scored: `deal_score = (median_price - asking_price) / median_price * 100`.
4. Results are stored in Supabase with tier labels: **excellent** (>20% below median), **good** (10–20%), **fair** (0–10%), **overpriced**.
5. The FastAPI backend exposes paginated, filterable endpoints for a frontend to consume.

---

## Setup Guide

### 1. Fork this repository

Click **Fork** on GitHub. All GitHub Actions workflows will run on your fork's schedule.

---

### 2. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) and create a free project.
2. In the **SQL Editor**, paste and run the contents of `database/schema.sql`.
3. Note your **Project URL** and **service-role API key** (found under Settings → API).

---

### 3. Add GitHub Secrets

In your forked repository, go to **Settings → Secrets and variables → Actions** and add:

| Secret name    | Value                                    |
|----------------|------------------------------------------|
| `SUPABASE_URL` | Your Supabase project URL                |
| `SUPABASE_KEY` | Your Supabase **service-role** API key   |

The scraper uses the service-role key so it can write through Row-Level Security.

---

### 4. Deploy the backend to Render.com

1. Go to [render.com](https://render.com) and create a new **Web Service**.
2. Connect your GitHub repository.
3. Set the following configuration:

   | Setting          | Value                          |
   |------------------|--------------------------------|
   | Root directory   | `backend`                      |
   | Build command    | `pip install -r requirements.txt` |
   | Start command    | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
   | Environment      | Python 3.11                    |

4. Add the same environment variables:
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `ALLOWED_ORIGINS` — your frontend domain, e.g. `https://myapp.vercel.app` (or `*` for open access during development)

5. Deploy. Your API will be live at `https://your-service.onrender.com`.

---

### 5. Verify the scraper runs automatically

Go to **Actions** in your GitHub repo. You should see two workflows:

- **Scrape Car Listings** — runs every 4 hours, also triggerable manually.
- **Cleanup Old Listings** — runs daily at midnight UTC, deletes listings older than 30 days.

Trigger **Scrape Car Listings** manually for an immediate first run.

---

## API Endpoints

All endpoints are relative to your Render deployment URL.

| Method | Path                    | Description                                                 |
|--------|-------------------------|-------------------------------------------------------------|
| GET    | `/health`               | Health check                                                |
| GET    | `/listings`             | Paginated listings, filterable by make/model/year/city/deal score |
| GET    | `/listings/top-deals`   | Top 50 deals (deal_score > 10%)                             |
| GET    | `/listings/stats`       | Market summary: total count, tier distribution, top makes   |
| GET    | `/listings/makes`       | Distinct makes for filter dropdowns                         |
| GET    | `/listings/models?make=Toyota` | Distinct models for a given make                   |

Interactive API docs: `https://your-service.onrender.com/docs`

---

## Project Structure

```
car-deal-finder/
├── scraper/
│   ├── scrapers/
│   │   ├── haraj.py          # haraj.com scraper
│   │   ├── syarah.py         # syarah.com scraper
│   │   └── motory.py         # motory.com scraper
│   ├── processors/
│   │   └── pricing_engine.py # deal scoring logic
│   ├── db/
│   │   └── supabase_client.py
│   ├── main.py               # scraper entry point
│   ├── cleanup.py            # delete old listings
│   └── requirements.txt
├── backend/
│   ├── main.py               # FastAPI app
│   ├── models.py             # Pydantic schemas
│   ├── routes/
│   │   └── listings.py       # REST endpoints
│   └── requirements.txt
├── database/
│   └── schema.sql            # Supabase PostgreSQL schema
└── .github/
    └── workflows/
        ├── scrape.yml        # every 4 hours
        └── cleanup.yml       # daily at midnight UTC
```

---

## Local Development

```bash
# Clone the repo
git clone https://github.com/your-username/car-deal-finder.git
cd car-deal-finder

# Create a .env file in scraper/ and backend/
echo "SUPABASE_URL=https://xxx.supabase.co" > scraper/.env
echo "SUPABASE_KEY=your-service-role-key" >> scraper/.env
cp scraper/.env backend/.env

# Install scraper deps and run a test scrape
cd scraper
pip install -r requirements.txt
python main.py

# Install backend deps and start the API server
cd ../backend
pip install -r requirements.txt
uvicorn main:app --reload
# API is now at http://localhost:8000
# Docs at http://localhost:8000/docs
```

---

## Notes

- **Rate limiting**: Each scraper sleeps 2–2.5 seconds between page requests.
- **JavaScript-heavy pages**: If a site switches to full client-side rendering, the scraper logs a warning. In that case, consider adding `playwright` or `selenium` as a fallback.
- **Market stats**: The `market_stats` materialized view in Supabase is designed to be refreshed via `SELECT refresh_market_stats()`. On paid Supabase plans, enable `pg_cron` and uncomment the scheduled refresh at the bottom of `schema.sql`.
- **Deal scoring**: Groups with fewer than 3 comparable listings still generate a score, but treat scores on small sample sizes (`sample_size < 3`) with caution.

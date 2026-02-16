<<<<<<< HEAD
# TrendTruth

TrendTruth is a hackathon project built to answer one simple question:

**"This story is trending everywhere... but how trustworthy is it?"**

The app pulls trending stories from multiple sources, checks supporting coverage, and gives each story a risk/credibility view so users can decide what to trust.

## What it does

- Fetches stories from:
  - Google News
  - Reddit
  - Hacker News
  - X (if API token is available, with fallback)
- Groups stories by sections like Local, India, World, Sports, Health, etc.
- Shows:
  - headline
  - summary
  - source + platform label
  - thumbnail
- Calculates:
  - `Risk %`
  - `Credibility %`
  - `Spread index`
- Includes a **"Why this rating?"** panel with supporting links.

## Tech stack

- Backend: FastAPI
- Frontend: HTML, CSS, Vanilla JavaScript
- APIs/feeds: Reddit JSON, Hacker News API, Google News RSS, optional X API

## Run it locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open in browser: `http://127.0.0.1:8000`

## Optional environment variable

If you have an X bearer token:

```bash
set X_BEARER_TOKEN=your_token_here
```

If no token is set, the app still works with other sources.

## API quick examples

- `GET /api/analyze?limit=20`
- `GET /api/analyze?limit=20&category=world`
- `GET /api/analyze?limit=20&category=india&query=election&refresh=true`

Available categories:

`all, local, india, world, entertainment, health, trending, sports, esports, food, events`

## Project structure

```text
app/
  main.py                  # FastAPI app + endpoints
  models.py                # Pydantic response models
  services/
    social_fetcher.py      # Fetch + enrich stories from sources
    verifier.py            # Evidence lookup and source checks
    scoring.py             # Risk/credibility/spread scoring
  static/
    index.html
    styles.css
    app.js
```

## Important note

TrendTruth is an analysis assistant, not a final fact-check authority.
Scores are probabilistic and should be read as indicators, not absolute truth labels.

## Team

Built by Team Sentinels during a hackathon.



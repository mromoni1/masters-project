# Napa Vine Advisor

A publicly accessible, climate-informed decision support system for small, independent Napa Valley vintners. Translates publicly available climate and agricultural data into plain-language wine advisories for growers who lack access to large-scale analytics platforms.

**Live site:** https://mromoni1.github.io/masters-project/

## Features

- **Historical Explorer** — compare predicted vs. actual harvest outcomes by variety and year (1992–2024)
- **Climate Trends** — 34-year view of growing degree days, heat stress, precipitation, Brix, and tonnage
- **Counterfactual Explorer** — ask "what would this harvest have looked like under a different climate year?"
- **Advisory Chat** — plain-language Q&A grounded in Napa climate and harvest data

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript, Vite, TailwindCSS 4 |
| Backend | FastAPI (Python), Anthropic Claude API |
| Frontend hosting | GitHub Pages |
| Backend hosting | Railway |

## Local Development

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Requires an `ANTHROPIC_API_KEY` in a `.env` file at the repo root.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server proxies `/api` requests to `http://localhost:8000`.

## Deployment

- **Frontend** — automatically deployed to GitHub Pages on every push to `main` via `.github/workflows/deploy.yml`
- **Backend** — deployed to Railway from the `backend/` directory; set `ANTHROPIC_API_KEY` in the Railway environment variables dashboard

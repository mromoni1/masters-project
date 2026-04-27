"""FastAPI backend for Napa Vine Advisor."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from advisory import generate  # noqa: E402
from chat import reply  # noqa: E402
from trends import get_data as trends_data, get_narrative as trends_narrative  # noqa: E402
from counterfactual import run as counterfactual_run  # noqa: E402

app = FastAPI(title="Napa Vine Advisor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

VALID_VARIETIES = {"Cabernet Sauvignon", "Pinot Noir", "Chardonnay"}


class AdvisoryRequest(BaseModel):
    variety: str
    year: int


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class CounterfactualRequest(BaseModel):
    variety: str
    base_year: int
    climate_year: int


@app.post("/api/advisory")
def advisory(req: AdvisoryRequest) -> dict:
    if req.variety not in VALID_VARIETIES:
        raise HTTPException(status_code=422, detail=f"Unknown variety: {req.variety}")
    if not (1992 <= req.year <= 2024):
        raise HTTPException(status_code=422, detail="Year must be between 1992 and 2024.")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured.")

    try:
        return generate(req.variety, req.year, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Advisory generation failed: {exc}") from exc


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    if not req.messages:
        raise HTTPException(status_code=422, detail="messages must not be empty.")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured.")

    try:
        text = reply(
            [{"role": m.role, "content": m.content} for m in req.messages],
            api_key,
        )
        return {"reply": text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chat failed: {exc}") from exc


@app.get("/api/trends")
def trends() -> dict:
    try:
        return trends_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Trends data failed: {exc}") from exc


@app.get("/api/trends/narrative")
def trends_narrative_route() -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured.")
    try:
        return {"narrative": trends_narrative(api_key)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Trends narrative failed: {exc}") from exc


@app.post("/api/counterfactual")
def counterfactual(req: CounterfactualRequest) -> dict:
    if req.variety not in VALID_VARIETIES:
        raise HTTPException(status_code=422, detail=f"Unknown variety: {req.variety}")
    if not (1992 <= req.base_year <= 2024):
        raise HTTPException(status_code=422, detail="base_year must be between 1992 and 2024.")
    if not (1991 <= req.climate_year <= 2024):
        raise HTTPException(status_code=422, detail="climate_year must be between 1991 and 2024.")
    if req.base_year == req.climate_year:
        raise HTTPException(status_code=422, detail="base_year and climate_year must differ.")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured.")

    try:
        return counterfactual_run(req.variety, req.base_year, req.climate_year, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Counterfactual failed: {exc}") from exc

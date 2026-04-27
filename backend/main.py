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

app = FastAPI(title="Napa Vine Advisor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["POST", "OPTIONS"],
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

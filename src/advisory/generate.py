"""LLM advisory layer — translates VintagePrediction into plain-language guidance.

Takes a structured VintagePrediction object and calls the Google Gemini API to
produce a concise, plain-language advisory suitable for an independent Napa
Valley vintner.

Design decisions
----------------
* Single-turn, non-streaming: the advisory is short (≤ 250 words) and the
  latency budget for this endpoint allows a synchronous call.
* Model: gemini-2.0-flash — fast, available on the Gemini free tier
  (API key from Google AI Studio, no billing required).
* Low-confidence predictions must open with a clear uncertainty caveat
  before presenting the estimate.
* No tool use, no agents: the LLM's only job is to render the structured
  data as grower-friendly prose.

Usage
-----
    from src.output.prediction import make_test_prediction
    from src.advisory.generate import generate_advisory

    prediction = make_test_prediction()
    advisory = generate_advisory(prediction)
    print(advisory)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from google import genai
from google.genai import types

if TYPE_CHECKING:
    from src.output.prediction import VintagePrediction

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "gemini-2.0-flash"

_SYSTEM_PROMPT = """\
You are an agricultural advisor writing plain-language vintage guidance for \
independent Napa Valley wine growers. Your growers are small-scale owner-operators \
who know their land intimately but do not have access to large-scale analytics platforms.

You will receive a structured prediction object for a single vintage. Your task is to \
translate it into clear, actionable prose — no jargon, no hedging beyond what the \
confidence level warrants, no generic filler.

STRICT RULES:
1. Base your advisory ONLY on the data provided in the prediction. Do not add \
information from outside the prediction (e.g., specific vineyard names, external \
forecasts, or market commentary).
2. When confidence is "low", you MUST open the advisory with a clear uncertainty \
caveat BEFORE presenting any estimate. Use plain language: e.g., \
"This season's combination of [stressors] means the model is working outside its \
historical comfort zone — treat the numbers below as directional, not precise."
3. When confidence is "moderate", acknowledge the uncertainty in one sentence \
before or after the estimate — do not lead with it unless the grower needs to \
act on it before harvest.
4. When confidence is "high", present the estimates directly without hedging.
5. Always include: predicted Brix and its range, predicted tonnage and its range, \
estimated harvest window, and one or two concrete management implications (e.g., \
timing of sugar monitoring, irrigation decisions, picking crews).
6. Write for a grower, not an agronomist. Avoid: "model extrapolation", \
"prediction interval", "residual standard deviation". Prefer: "our best estimate", \
"expect somewhere between X and Y", "watch closely from [date]".
7. Maximum 250 words. No bullet lists — prose only.
8. Do not include a subject line, greeting, or sign-off.
"""


# ---------------------------------------------------------------------------
# Advisory generation
# ---------------------------------------------------------------------------

def generate_advisory(
    prediction: "VintagePrediction",
    api_key: str | None = None,
) -> str:
    """Generate a plain-language vintage advisory from a structured prediction.

    Calls the Google Gemini API (gemini-2.0-flash) with the structured
    prediction as the user message and the advisory rules as the system prompt.

    Args:
        prediction: A fully populated VintagePrediction from src.output.prediction.
        api_key: Gemini API key. Defaults to GEMINI_API_KEY env var.

    Returns:
        Plain-text advisory string (≤ 250 words).

    Raises:
        google.genai.errors.APIError: If the API call fails.
        ValueError: If GEMINI_API_KEY is not set and api_key is not provided.
    """
    resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not resolved_key:
        raise ValueError(
            "Gemini API key not found. Set GEMINI_API_KEY in your environment "
            "or pass api_key= to generate_advisory(). "
            "Get a free key at Google AI Studio."
        )

    client = genai.Client(api_key=resolved_key)

    response = client.models.generate_content(
        model=MODEL,
        contents=_format_prediction_message(prediction),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            max_output_tokens=512,
            temperature=0.3,
        ),
    )

    return response.text.strip()


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def _format_prediction_message(prediction: "VintagePrediction") -> str:
    """Serialise a VintagePrediction into a structured prompt for the LLM.

    Renders the prediction as a labelled key-value block so the model receives
    clean, unambiguous inputs. The confidence note (already generated by the
    classification logic) is included verbatim so the LLM knows which stressors
    drove the rating.

    Args:
        prediction: Structured prediction object.

    Returns:
        User-turn string ready to be sent to the model.
    """
    brix_lo, brix_hi = prediction.brix_range
    ton_lo, ton_hi = prediction.tonnage_range

    return f"""\
Please write a vintage advisory using the following prediction data.

VARIETY:             {prediction.variety}
AVA DISTRICT:        {prediction.ava_district}
HARVEST YEAR:        {prediction.season_year}

BRIX ESTIMATE:       {prediction.brix_predicted:.1f} °Brix
BRIX RANGE (90%):    {brix_lo:.1f} – {brix_hi:.1f} °Brix

TONNAGE ESTIMATE:    {prediction.tonnage_predicted:.2f} tons/acre
TONNAGE RANGE (90%): {ton_lo:.2f} – {ton_hi:.2f} tons/acre

HARVEST WINDOW:      {prediction.harvest_window}

CONFIDENCE LEVEL:    {prediction.confidence.upper()}
CONFIDENCE NOTE:     {prediction.confidence_note}
"""

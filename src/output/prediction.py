"""Structured prediction output layer.

Converts raw model predictions into a VintagePrediction object with
confidence classification and harvest window estimation. This sits between
the trained model and the LLM advisory layer.

VintagePrediction schema
------------------------
    variety            : str   – "Cabernet Sauvignon" / "Pinot Noir" / "Chardonnay"
    ava_district       : str   – TTB-recognised Napa AVA name
    season_year        : int   – harvest calendar year
    brix_predicted     : float – point estimate
    brix_range         : tuple[float, float] – (lower, upper) prediction interval
    tonnage_predicted  : float – point estimate (tons/acre)
    tonnage_range      : tuple[float, float]
    harvest_window     : str   – e.g. "late September – early October"
    confidence         : str   – "high" / "moderate" / "low"
    confidence_note    : str   – plain-language explanation of confidence level

Confidence classification
-------------------------
High    – prediction within historical distribution, all key features present,
          season follows a recognisable pattern.
Moderate – one or more features missing/imputed, or the season sits near the
           boundary of the training distribution.
Low     – unusual season: any two of {late frost, above-threshold heat stress,
          drought year}. Model is extrapolating outside familiar territory.

Harvest window estimation
--------------------------
Variety-specific typical windows (Napa Valley historical range) are shifted
earlier or later based on whether the predicted Brix sits above or below the
variety's historical mean. A high-Brix season indicates earlier maturity;
a low-Brix season indicates later maturity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Napa Valley historical mean Brix by variety (approximate, from CDFA records)
_VARIETY_MEAN_BRIX: dict[str, float] = {
    "Cabernet Sauvignon": 24.5,
    "Pinot Noir": 23.8,
    "Chardonnay": 23.2,
}

# Harvest window anchors: (early_start, early_end, late_start, late_end)
# Each is a (month_name, ordinal) tuple where ordinal is "early"/"mid"/"late"
_HARVEST_WINDOWS: dict[str, tuple[str, str]] = {
    # variety: (early_window, late_window) — shift based on Brix deviation
    "Cabernet Sauvignon": ("mid-September", "late October"),
    "Pinot Noir":         ("mid-August",    "late September"),
    "Chardonnay":         ("early August",  "mid-September"),
}

# Brix deviation threshold (from variety mean) to shift window earlier/later
_BRIX_SHIFT_THRESHOLD = 0.8  # ± 0.8 Brix triggers a window shift

# Season stress thresholds for confidence classification
_HEAT_STRESS_HIGH = 12   # heat_stress_days above this is "elevated"
_HEAT_STRESS_MODERATE = 6


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VintagePrediction:
    """Structured output of a single vintage quality/yield prediction."""

    variety: str
    ava_district: str
    season_year: int

    brix_predicted: float
    brix_range: tuple[float, float]

    tonnage_predicted: float
    tonnage_range: tuple[float, float]

    harvest_window: str

    confidence: Literal["high", "moderate", "low"]
    confidence_note: str

    def as_dict(self) -> dict[str, Any]:
        """Return a plain dict representation suitable for JSON serialisation."""
        return {
            "variety": self.variety,
            "ava_district": self.ava_district,
            "season_year": self.season_year,
            "brix_predicted": self.brix_predicted,
            "brix_range": list(self.brix_range),
            "tonnage_predicted": self.tonnage_predicted,
            "tonnage_range": list(self.tonnage_range),
            "harvest_window": self.harvest_window,
            "confidence": self.confidence,
            "confidence_note": self.confidence_note,
        }


# ---------------------------------------------------------------------------
# Confidence classification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeasonContext:
    """Climate stress context used to classify prediction confidence.

    Attributes:
        frost_days: Days with tmin < 0 °C in Mar–May.
        heat_stress_days: Days with tmax > 35 °C in Apr–Oct.
        is_dry: True if DWR water year classification is D or C.
        features_complete: False if any key model input was NaN or imputed.
    """

    frost_days: int
    heat_stress_days: int
    is_dry: bool
    features_complete: bool = True


def classify_confidence(
    context: SeasonContext,
) -> tuple[Literal["high", "moderate", "low"], str]:
    """Determine confidence level and generate an explanatory note.

    Logic:
    - Low  : any two or more of {frost_days > 0, heat_stress_days high, is_dry}
             → model is extrapolating beyond familiar training patterns.
    - Moderate: any one stressor present, or features incomplete.
    - High : no stressors, all features present.

    Args:
        context: SeasonContext with climate stress indicators.

    Returns:
        Tuple of (confidence_level, plain-language note).
    """
    stressors: list[str] = []

    if context.frost_days > 0:
        stressors.append(
            f"late frost ({context.frost_days} frost day"
            f"{'s' if context.frost_days > 1 else ''} in spring)"
        )
    if context.heat_stress_days >= _HEAT_STRESS_HIGH:
        stressors.append(
            f"elevated heat stress ({context.heat_stress_days} days above 35 °C)"
        )
    if context.is_dry:
        stressors.append("drought water year (D or C classification)")

    if len(stressors) >= 2:
        note = (
            "Low confidence: this season combines multiple stress factors — "
            + " and ".join(stressors)
            + ". The model is extrapolating beyond its typical training range; "
            "treat this estimate as directional only."
        )
        return "low", note

    if len(stressors) == 1 or not context.features_complete:
        parts: list[str] = []
        if stressors:
            parts.append(stressors[0])
        if not context.features_complete:
            parts.append("one or more input features were missing or imputed")
        note = (
            "Moderate confidence: "
            + "; ".join(parts)
            + ". The prediction is plausible but carry wider uncertainty."
        )
        return "moderate", note

    return "high", (
        "High confidence: season conditions are within the model's historical "
        "training range and all input features are complete."
    )


# ---------------------------------------------------------------------------
# Harvest window estimation
# ---------------------------------------------------------------------------

def estimate_harvest_window(variety: str, brix_predicted: float) -> str:
    """Return a plain-language harvest window string.

    Shifts the variety's typical window earlier if predicted Brix is above the
    variety mean (advanced maturity) and later if below (delayed maturity).

    Args:
        variety: One of "Cabernet Sauvignon", "Pinot Noir", "Chardonnay".
        brix_predicted: Model's Brix point estimate.

    Returns:
        Plain-language string, e.g. "mid-September to early October".
    """
    early_anchor, late_anchor = _HARVEST_WINDOWS.get(
        variety, ("mid-September", "late October")
    )
    mean_brix = _VARIETY_MEAN_BRIX.get(variety, 24.0)
    deviation = brix_predicted - mean_brix

    if deviation >= _BRIX_SHIFT_THRESHOLD:
        # Above-average Brix → shift toward the early end
        return f"early to {early_anchor}"
    elif deviation <= -_BRIX_SHIFT_THRESHOLD:
        # Below-average Brix → shift toward the late end
        return f"{late_anchor} to early November" if "Cabernet" in variety else f"{late_anchor}"
    else:
        # Near-average → full typical window
        return f"{early_anchor} to {late_anchor}"


# ---------------------------------------------------------------------------
# Prediction interval helper
# ---------------------------------------------------------------------------

def _make_interval(
    point: float, residual_std: float, z: float = 1.645
) -> tuple[float, float]:
    """Return a symmetric prediction interval around a point estimate.

    Uses a normal approximation: point ± z * residual_std.
    Default z=1.645 gives a ~90% interval.

    Args:
        point: Model point estimate.
        residual_std: Standard deviation of residuals from model evaluation.
        z: Z-score multiplier for the interval width.

    Returns:
        (lower, upper) rounded to 2 decimal places.
    """
    margin = z * residual_std
    return (round(point - margin, 2), round(point + margin, 2))


# ---------------------------------------------------------------------------
# Main predict() function
# ---------------------------------------------------------------------------

def predict(
    variety: str,
    ava_district: str,
    season_year: int,
    features: dict[str, Any],
    model: Any,
    brix_residual_std: float,
    tonnage_residual_std: float,
) -> VintagePrediction:
    """Generate a structured vintage prediction from a trained model.

    Args:
        variety: Grape variety name.
        ava_district: AVA district name.
        season_year: Harvest year.
        features: Feature dict matching the model's expected input columns.
                  Must include 'frost_days', 'heat_stress_days', 'is_dry'.
        model: Trained multi-output model with a predict() method that accepts
               a 2-D array/DataFrame and returns [[brix, tonnage]].
        brix_residual_std: Std dev of brix residuals from model evaluation
                           (used to build the prediction interval).
        tonnage_residual_std: Std dev of tonnage residuals.

    Returns:
        VintagePrediction with all fields populated.
    """
    import pandas as pd

    # Model prediction
    feature_df = pd.DataFrame([features])
    raw = model.predict(feature_df)
    brix_pred = float(raw[0][0])
    tonnage_pred = float(raw[0][1])

    # Prediction intervals
    brix_range = _make_interval(brix_pred, brix_residual_std)
    tonnage_range = _make_interval(tonnage_pred, tonnage_residual_std)

    # Confidence classification
    context = SeasonContext(
        frost_days=int(features.get("frost_days", 0)),
        heat_stress_days=int(features.get("heat_stress_days", 0)),
        is_dry=bool(features.get("is_dry", False)),
        features_complete=not any(
            v is None or (isinstance(v, float) and v != v)  # NaN check
            for k, v in features.items()
            if k in ("gdd", "winkler_index", "precip_winter", "eto_season")
        ),
    )
    confidence, confidence_note = classify_confidence(context)

    # Harvest window
    harvest_window = estimate_harvest_window(variety, brix_pred)

    return VintagePrediction(
        variety=variety,
        ava_district=ava_district,
        season_year=season_year,
        brix_predicted=round(brix_pred, 2),
        brix_range=brix_range,
        tonnage_predicted=round(tonnage_pred, 2),
        tonnage_range=tonnage_range,
        harvest_window=harvest_window,
        confidence=confidence,
        confidence_note=confidence_note,
    )


# ---------------------------------------------------------------------------
# Factory for testing / advisory layer development
# ---------------------------------------------------------------------------

def make_test_prediction(
    variety: str = "Cabernet Sauvignon",
    ava_district: str = "Oakville",
    season_year: int = 2024,
    brix: float = 24.8,
    tonnage: float = 3.2,
    frost_days: int = 0,
    heat_stress_days: int = 4,
    is_dry: bool = False,
    brix_std: float = 0.6,
    tonnage_std: float = 0.4,
) -> VintagePrediction:
    """Build a VintagePrediction directly from raw values for testing.

    Bypasses the trained model so the advisory layer can be developed and
    tested before model training is complete.

    Args:
        variety: Grape variety.
        ava_district: AVA district.
        season_year: Harvest year.
        brix: Predicted Brix value.
        tonnage: Predicted tonnage (tons/acre).
        frost_days: Spring frost days (for confidence classification).
        heat_stress_days: Growing season heat stress days.
        is_dry: Whether the DWR water year is D or C.
        brix_std: Residual std used to build Brix interval.
        tonnage_std: Residual std used to build tonnage interval.

    Returns:
        VintagePrediction ready for passing to the advisory layer.
    """
    context = SeasonContext(
        frost_days=frost_days,
        heat_stress_days=heat_stress_days,
        is_dry=is_dry,
    )
    confidence, confidence_note = classify_confidence(context)
    harvest_window = estimate_harvest_window(variety, brix)

    return VintagePrediction(
        variety=variety,
        ava_district=ava_district,
        season_year=season_year,
        brix_predicted=round(brix, 2),
        brix_range=_make_interval(brix, brix_std),
        tonnage_predicted=round(tonnage, 2),
        tonnage_range=_make_interval(tonnage, tonnage_std),
        harvest_window=harvest_window,
        confidence=confidence,
        confidence_note=confidence_note,
    )

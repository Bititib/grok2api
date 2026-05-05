"""Pricing engine — cost calculation per model and endpoint.

Reads pricing config from ``[billing.pricing]`` in config.toml.  Falls back
to sensible defaults when no config is present.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.platform.config.snapshot import get_config


@dataclass(slots=True)
class ModelPricing:
    """Pricing for one model.

    For token-based models:  input/output are price per 1M tokens.
    For per-request models:  per_request is fixed cost per call.
    For video models:        video_cost_fn calculates based on seconds.
    """
    input: float = 0.0
    output: float = 0.0
    per_request: float = 0.0
    is_video: bool = False


# ---------------------------------------------------------------------------
# Default pricing table (used when config has no [billing.pricing])
# ---------------------------------------------------------------------------

_DEFAULT_PRICING: dict[str, ModelPricing] = {
    # Chat models — per 1M tokens
    "grok-3":              ModelPricing(input=3.0,  output=15.0),
    "grok-3-mini":         ModelPricing(input=0.3,  output=0.5),
    "grok-3-fast":         ModelPricing(input=0.6,  output=3.0),
    "grok-4":              ModelPricing(input=3.0,  output=15.0),
    "grok-4-mini":         ModelPricing(input=0.3,  output=0.5),
    # Image models — per request
    "grok-imagine-image":      ModelPricing(per_request=0.04),
    "grok-imagine-image-lite": ModelPricing(per_request=0.02),
    "grok-imagine-image-pro":  ModelPricing(per_request=0.06),
    "grok-image-edit":         ModelPricing(per_request=0.04),
    # Video models — will use video_cost()
    "grok-imagine-video":      ModelPricing(is_video=True),
    "grok-video":              ModelPricing(is_video=True),
    "grok-4.3-video":          ModelPricing(is_video=True),
    "grok-4.3-video-heavy":    ModelPricing(is_video=True),
}


def video_cost(seconds: int) -> float:
    """Calculate video cost based on duration.

    Rules (from user spec):
    - ≤ 20s  → 0.1
    - 20s    → 0.2
    - 30s    → 0.3
    - Otherwise scale linearly per 10s = 0.1
    """
    cfg = get_config()
    # Allow override via config
    base = cfg.get_float("billing.video_base_cost", 0.1)

    if seconds <= 10:
        return base          # 0.1
    elif seconds <= 16:
        return base          # 0.1
    elif seconds == 20:
        return round(base * 2, 4)      # 0.2
    elif seconds == 30:
        return round(base * 3, 4)      # 0.3
    else:
        # Linear: 0.01 per second
        return round(seconds * 0.01, 4)


def get_pricing(model: str) -> ModelPricing:
    """Get pricing for a model, checking config first then defaults."""
    cfg = get_config()

    # Try config-based pricing
    input_price = cfg.get_float(f"billing.pricing.{model}.input", -1)
    output_price = cfg.get_float(f"billing.pricing.{model}.output", -1)
    per_req = cfg.get_float(f"billing.pricing.{model}.per_request", -1)

    if input_price >= 0 or output_price >= 0:
        return ModelPricing(
            input=max(0, input_price),
            output=max(0, output_price),
        )
    if per_req >= 0:
        return ModelPricing(per_request=per_req)

    # Fallback to default table
    if model in _DEFAULT_PRICING:
        return _DEFAULT_PRICING[model]

    # Unknown model — try to match prefix
    for prefix, pricing in _DEFAULT_PRICING.items():
        if model.startswith(prefix):
            return pricing

    # Truly unknown — use a conservative default
    return ModelPricing(input=1.0, output=3.0)


def calculate_cost(
    model: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    video_seconds: int = 0,
    endpoint: str = "",
) -> float:
    """Calculate the cost of one API call."""
    pricing = get_pricing(model)

    # Video models
    if pricing.is_video or endpoint == "video":
        return video_cost(video_seconds)

    # Per-request models (images)
    if pricing.per_request > 0:
        return pricing.per_request

    # Token-based models
    cost = (
        prompt_tokens * pricing.input / 1_000_000
        + completion_tokens * pricing.output / 1_000_000
    )
    return round(cost, 8)


__all__ = ["get_pricing", "calculate_cost", "video_cost", "ModelPricing"]

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


def video_cost(seconds: int, resolution: str = "720p", model: str | None = None) -> float:
    """Calculate video cost based on duration and resolution.

    Per-second pricing by resolution:
    - 480p → $0.02 / second
    - 720p → $0.03 / second

    Rates are overridable via config:
    - billing.video_cost_per_second_480p
    - billing.video_cost_per_second_720p
    """
    cfg = get_config()

    if model:
        # Try model specific pricing first
        rate = cfg.get_float(f"billing.pricing.{model}.video_cost_per_second_{resolution}", -1.0)
        if rate >= 0:
            return round(seconds * rate, 4)

    if resolution == "480p":
        rate = cfg.get_float("billing.video_cost_per_second_480p", 0.02)
    else:
        # 720p and any other resolution default to 720p rate
        rate = cfg.get_float("billing.video_cost_per_second_720p", 0.03)

    return round(seconds * rate, 4)


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

    # Truly unknown — use NewAPI default pricing from config, or conservative default
    return ModelPricing(
        input=cfg.get_float("providers.newapi.default_input_price", 1.0),
        output=cfg.get_float("providers.newapi.default_output_price", 3.0),
    )


def calculate_cost(
    model: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    video_seconds: int = 0,
    video_resolution: str = "720p",
    endpoint: str = "",
) -> float:
    """Calculate the cost of one API call."""
    pricing = get_pricing(model)

    # Video models
    if pricing.is_video or endpoint == "video":
        return video_cost(video_seconds, resolution=video_resolution, model=model)

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

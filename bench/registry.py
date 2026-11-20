"""Token Factory serverless models. The only place a model ID or a price lives.

Prices read 2026-11-20 from https://www.sarvam.ai/token-factory/pricing
and https://docs.sarvam.ai/api/getting-started/pricing - excluding GST.
Three models are on introductory pricing through the end of 2026.
Do not edit a price without changing PRICES_READ_ON and the source URL.
"""

PRICES_READ_ON = "2026-11-20"
PRICING_URL = "https://www.sarvam.ai/token-factory/pricing"

MODELS = {
    "sarvam-105b": dict(
        context=128_000, input_modalities=("text",), reasoning_default="low",
        introductory=True, **{"in": 10.0, "cached": 0.25, "out": 25.0},
    ),
    "sarvam-105b-conversations": dict(
        context=32_000, input_modalities=("text",), reasoning_default=None,
        introductory=True, **{"in": 10.0, "cached": 0.25, "out": 25.0},
    ),
    "glm5.3": dict(
        context=1_048_576, input_modalities=("text",), reasoning_default="max",
        introductory=False, **{"in": 126.0, "cached": 20.0, "out": 390.0},
    ),
    "glm5.3-flash": dict(
        context=1_048_576, input_modalities=("text", "image"), reasoning_default="high",
        introductory=False, **{"in": 13.5, "cached": 2.5, "out": 45.0},
    ),
    "gemma4": dict(
        context=262_144, input_modalities=("text", "image"), reasoning_default=None,
        introductory=False, **{"in": 35.0, "cached": 10.0, "out": 90.0},
    ),
    "deepseekv4.1-flash-1017": dict(
        context=1_048_576, input_modalities=("text", "image"), reasoning_default="high",
        introductory=True, **{"in": 14.0, "cached": 0.25, "out": 55.0},
    ),
}


def cost_inr(model: str, prompt_tokens: int, completion_tokens: int,
             cached_tokens: int = 0) -> float:
    """Rupees for one call, from the API's own token counts. No estimating."""
    m = MODELS[model]
    billable_in = max(prompt_tokens - cached_tokens, 0)
    return round(
        billable_in / 1e6 * m["in"]
        + cached_tokens / 1e6 * m["cached"]
        + completion_tokens / 1e6 * m["out"],
        6,
    )

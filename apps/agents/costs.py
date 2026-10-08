"""Turns token counts into an estimated cost in US dollars.

Prices are per million tokens and come from settings, so they can be changed in
.env when the provider changes its prices or the model is swapped.
"""

from decimal import Decimal

from django.conf import settings

MILLION = Decimal(1_000_000)
SIX_PLACES = Decimal("0.000001")


def estimate_cost(input_tokens, output_tokens):
    """What these tokens cost at the listed price, to six decimal places."""
    cost = (
        Decimal(input_tokens or 0) * Decimal(str(settings.LLM_INPUT_PRICE))
        + Decimal(output_tokens or 0) * Decimal(str(settings.LLM_OUTPUT_PRICE))
    ) / MILLION
    return cost.quantize(SIX_PLACES)

"""Claude API list prices (USD per million tokens), for cost *estimates*.

Source: Anthropic published pricing as of 2026-11-03 (first-party API). Costs are estimates:
the bill from Anthropic is authoritative. Unknown models return ``None`` — JACK never guesses
a price.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

PRICES_AS_OF = "2026-11-03"
D = Decimal


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    # Haiku 5.5 charges more above a prompt-size threshold.
    long_threshold: int | None = None
    long_input: Decimal | None = None
    long_output: Decimal | None = None


def _p(i: str, o: str, read: str | None = None) -> Price:
    return Price(D(i), D(o), D(read) if read is not None else D(i) * D("0.1"))


PRICES: dict[str, Price] = {
    "claude-fable-5-2": _p("8", "40", "0.20"),
    "claude-mythos-5-2": _p("8", "40", "0.20"),
    "claude-fable-5-1": _p("10", "50", "0.25"),
    "claude-mythos-5-1": _p("10", "50", "0.25"),
    "claude-fable-5": _p("10", "50", "1"),
    "claude-mythos-5": _p("10", "50", "1"),
    "claude-opus-5-5": _p("4", "20", "0.20"),
    "claude-opus-5": _p("5", "25"),
    "claude-opus-4-8": _p("5", "25"),
    "claude-opus-4-7": _p("5", "25"),
    "claude-opus-4-6": _p("5", "25"),
    "claude-sonnet-5-5": _p("2", "10", "0.10"),
    "claude-sonnet-5": _p("2", "10"),
    "claude-sonnet-4-6": _p("3", "15"),
    "claude-haiku-5-5": Price(D("0.10"), D("0.50"), D("0.01"), 100_000, D("0.50"), D("2.50")),
    "claude-haiku-4-5": _p("1", "5"),
}

CACHE_WRITE_5M = D("1.25")
CACHE_WRITE_1H = D("2")
MILLION = D(1_000_000)


def price_for(model: str) -> Price | None:
    if model in PRICES:
        return PRICES[model]
    # Tolerate provider prefixes / suffixes that still identify the same model.
    for known, price in PRICES.items():
        if model.endswith(known):
            return price
    return None


def estimate(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0,
             cache_write_5m: int = 0, cache_write_1h: int = 0) -> Decimal | None:
    p = price_for(model)
    if p is None:
        return None
    prompt = input_tokens + cache_read + cache_write_5m + cache_write_1h
    in_rate, out_rate = p.input, p.output
    if p.long_threshold is not None and prompt > p.long_threshold:
        in_rate, out_rate = p.long_input or in_rate, p.long_output or out_rate
    cost = (D(input_tokens) * in_rate + D(output_tokens) * out_rate
            + D(cache_read) * p.cache_read + D(cache_write_5m) * in_rate * CACHE_WRITE_5M
            + D(cache_write_1h) * in_rate * CACHE_WRITE_1H) / MILLION
    return cost.quantize(D("0.000001"))

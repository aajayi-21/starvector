"""Measure what one instant send costs at the model provider.

Spec IM1 build item IM1.2 and decision D4. One instant send is one
encode: the sketch and the typed rows of the send go to the encoders of
the scoring configuration. The cap on the sends of one date,
`instant_day_cap` in the server configuration, is the bound on that
cost. This tool measures the cost of one send, thus the owner can set
the cap from a budget.

It encodes three sample sends with the live encoders and a new, empty
cache, thus each sample is a paid POST. It reads the token counts and
the cost that the provider gives with each answer, and the time of each
encode. It needs
the API key in the environment and the network, and it writes nothing
to the store and nothing to the vector cache of the deployment:

    OPENROUTER_API_KEY=... uv run python -m tools.instant_cost \\
        --config configs/scoring/prod-wit-mixed.json --budget-usd 1

The cost of this measurement is the cost of the three samples.
"""

import argparse
import math
import os
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The three sample sends: a sketch with words and a labeled part, words
# alone, and a sketch alone. A player sends one of these three shapes.
SAMPLES: dict[str, dict] = {
    "sketch and words": {
        "impressions": ["tall vertical structure", "cold and exposed"],
        "canvas_strokes": [
            {"points": [[0.1, 0.4], [0.3, 0.4], [0.3, 0.6], [0.1, 0.6],
                        [0.1, 0.4]], "group_id": "g1"},
            {"points": [[0.6, 0.4], [0.9, 0.4], [0.9, 0.6], [0.6, 0.6],
                        [0.6, 0.4]], "group_id": None},
        ],
        "groups": [{"id": "g1", "label": "tower"}],
        "relations": [],
        "pasted_text": None,
    },
    "words alone": {
        "impressions": ["a narrow street", "wet stone", "evening"],
        "canvas_strokes": [], "groups": [], "relations": [],
        "pasted_text": None,
    },
    "sketch alone": {
        "impressions": [],
        "canvas_strokes": [
            {"points": [[0.2, 0.2], [0.5, 0.7], [0.8, 0.3], [0.2, 0.2]],
             "group_id": None},
            {"points": [[0.3, 0.8], [0.7, 0.8], [0.5, 0.5], [0.3, 0.8]],
             "group_id": None},
        ],
        "groups": [], "relations": [], "pasted_text": None,
    },
}


class UsageClient:
    """An OpenRouter client that keeps the counts of each answer.

    The provider gives an object with the token counts and the cost of
    each POST. This class keeps each one.

    It gives each POST to the client that it holds. The encoders read
    two names of a client, and this class has the two.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.usages: list[dict] = []

    @property
    def post_count(self) -> int:
        return self._inner.post_count   # type: ignore[attr-defined]

    def post_embeddings(self, body: Mapping[str, object]) -> dict:
        response = self._inner.post_embeddings(body)  # type: ignore[attr-defined]
        usage = response.get("usage")
        self.usages.append(dict(usage) if isinstance(usage, dict) else {})
        return response


@dataclass(frozen=True, slots=True)
class SampleCost:
    """What one sample send cost: its POSTs, its time, and its counts.

    The last field sums each number that the provider gave with the
    answers of this sample. cost is the cost number of that sum in USD,
    or None when the provider gave none.
    """

    name: str
    posts: int
    seconds: float
    usage: dict[str, float]

    @property
    def cost(self) -> float | None:
        value = self.usage.get("cost")
        return None if value is None else float(value)


def sum_usage(usages: Sequence[Mapping[str, object]]) -> dict[str, float]:
    """The sum of each number in the count objects of a provider.

    A value that is not a number is not in the sum: a provider can put
    text or a nested object there.
    """
    total: dict[str, float] = {}
    for usage in usages:
        for name, value in usage.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            total[name] = total.get(name, 0.0) + float(value)
    return total


def cap_for_budget(budget_usd: float, cost_of_one_send: float) -> int:
    """The largest count of sends that a budget pays for.

    The cap of spec IM1 decision D4: the budget of one date divided by
    the cost of one send, with the fraction dropped. A cost of zero or
    less raises: it gives no bound.
    """
    if budget_usd <= 0:
        raise ValueError("the budget must be above zero")
    if cost_of_one_send <= 0:
        raise ValueError("the cost of one send must be above zero")
    return math.floor(budget_usd / cost_of_one_send)


def measure(config_path: Path, client: UsageClient, cache_root: Path,
            samples: Mapping[str, dict] | None = None) -> list[SampleCost]:
    """Encode each sample send one time, and give what each one cost.

    The encoders are the two OpenRouter slots of the scoring
    configuration, with cache_root as their cache. An empty cache makes
    each sample a POST. A configuration with a different provider
    raises: this tool measures the provider that asks for money.
    """
    from core.intake import validate_submission
    from core.types import RenderParams
    from pipeline.config import intake_gates, load_scoring_config
    from pipeline.context import load_preparation_record
    from pipeline.score import Encoders, encode_submission
    from pool.preparation.config import load_preparation_config
    from providers.openrouter.embeddings import (EmbeddingSlotConfig,
                                                 OpenRouterImageEncoder,
                                                 OpenRouterTextEncoder)

    config = load_scoring_config(config_path)
    slots = config.providers
    for name, slot in (("sketch_encoder", slots.sketch_encoder),
                       ("text_encoder", slots.text_encoder)):
        if slot.provider != "openrouter":
            raise ValueError(
                f"{config_path}: the {name} slot has the provider "
                f"{slot.provider!r} - this tool measures OpenRouter slots")
    section = slots.openrouter
    sketch = OpenRouterImageEncoder(
        EmbeddingSlotConfig(
            slot="sketch_encoder",
            model=slots.sketch_encoder.model or section.default_model,
            dimension=slots.sketch_encoder.dimension or 0,
            encoding_format="float",
            instruction=slots.sketch_encoder.instruction_template),
        client, cache_root)       # type: ignore[arg-type]
    text = OpenRouterTextEncoder(
        EmbeddingSlotConfig(
            slot="text_encoder",
            model=slots.text_encoder.model or section.default_model,
            dimension=slots.text_encoder.dimension or 0,
            encoding_format="float",
            instruction=slots.text_encoder.instruction_template),
        client, cache_root)       # type: ignore[arg-type]
    record = load_preparation_record(Path(config.input.preparation_record))
    linedraw = load_preparation_config(Path(record.config_path)).linedraw
    render = RenderParams(canvas_px=linedraw.canvas_px,
                          line_width_px=linedraw.line_width_px,
                          stroke_color=linedraw.stroke_color)
    gates = intake_gates(config)
    encoders = Encoders(sketch=sketch, text=text)

    found = []
    for name, wire in (samples or SAMPLES).items():
        submission = validate_submission(wire, gates, render.canvas_px)
        posts, answers = client.post_count, len(client.usages)
        started = time.perf_counter()
        encode_submission(submission, render, encoders)
        found.append(SampleCost(
            name=name, posts=client.post_count - posts,
            seconds=time.perf_counter() - started,
            usage=sum_usage(client.usages[answers:])))
    return found


def report_lines(samples: Sequence[SampleCost],
                 budget_usd: float | None) -> list[str]:
    """The lines that the owner reads: each sample, the largest cost,
    and the cap that a budget gives.

    The cap reads the most expensive sample, thus a date of such sends
    stays in the budget.
    """
    lines = []
    for sample in samples:
        cost = "no cost number" if sample.cost is None \
            else f"USD {sample.cost:.6f}"
        tokens = sample.usage.get("total_tokens",
                                  sample.usage.get("prompt_tokens"))
        lines.append(
            f"{sample.name}: {sample.posts} POST(s), "
            f"{sample.seconds:.2f} s, "
            + ("no token count" if tokens is None
               else f"{int(tokens)} tokens") + f", {cost}")
    costs = [sample.cost for sample in samples if sample.cost is not None]
    if len(costs) != len(samples) or not costs:
        lines.append(
            "The provider gave no cost number for one sample or more. "
            "Read the cost of these POSTs on the activity page of the "
            "provider, and divide the budget by the largest one.")
        return lines
    largest = max(costs)
    lines.append(f"largest cost of one send: USD {largest:.6f}")
    lines.append(f"sends for USD 1: {cap_for_budget(1.0, largest)}")
    if budget_usd is not None:
        lines.append(
            f"instant_day_cap for USD {budget_usd:g} on one date: "
            f"{cap_for_budget(budget_usd, largest)}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.instant_cost")
    parser.add_argument("--config", type=Path,
                        default=Path("configs/scoring/prod-wit-mixed.json"))
    parser.add_argument("--budget-usd", type=float, default=None,
                        help="the budget of one date; the tool prints the "
                             "cap that it pays for")
    arguments = parser.parse_args(argv)
    sys.path.insert(0, str(REPO))
    from pipeline.config import load_scoring_config
    from providers.openrouter.client import (OpenRouterClient,
                                             OpenRouterClientConfig)

    try:
        section = load_scoring_config(arguments.config).providers.openrouter
        inner = OpenRouterClient(
            OpenRouterClientConfig(
                max_concurrency=section.max_concurrency,
                requests_per_second=section.requests_per_second,
                timeout_seconds=section.timeout_seconds,
                retry_limit=section.retry_limit),
            api_key=os.environ.get("OPENROUTER_API_KEY", ""))
        with tempfile.TemporaryDirectory() as cache_root:
            samples = measure(arguments.config, UsageClient(inner),
                              Path(cache_root))
    except Exception as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    for line in report_lines(samples, arguments.budget_usd):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

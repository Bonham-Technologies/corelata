"""`corelata bench` (spec §13, §14 M6): the shipped scenario sets and the runner that plays them
against real models. Only the data paths live here; the runner is `corelata.bench.run`, the
result schema `corelata.bench.schema`, so importing the package never imports the pipeline.
Two sets ship (R-M12-4): `synthetic`, written for the synthetic model's markers and the one CI
runs, and `real`, written for real models."""

from pathlib import Path

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
REAL_SCENARIOS_DIR = Path(__file__).parent / "scenarios-real"
SCENARIO_SETS: dict[str, Path] = {"synthetic": SCENARIOS_DIR, "real": REAL_SCENARIOS_DIR}


def scenarios_path(value: str) -> Path:
    """`--scenarios`: a shipped set by name, else a directory path (write `./real` for a
    directory that happens to be called `real`)."""
    return SCENARIO_SETS.get(value, Path(value))

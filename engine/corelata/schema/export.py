"""Export JSON Schema for the canonical models. Usage: python -m corelata.schema.export DIR"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from corelata.bench.schema import BenchReport
from corelata.schema import (
    DiscoveryResult,
    DiscoveryView,
    DoctorReport,
    Report,
    RunProgress,
    RunRecord,
    RunSummary,
)
from corelata.standards.loader import PackSummary
from corelata.standards.schema import ResolvedPack
from corelata.trace import ClaimProvenance, RunTrace, TraceSummary

EXPORTED: dict[str, type[BaseModel]] = {
    "report": Report,
    "run-record": RunRecord,
    "resolved-pack": ResolvedPack,
    "discovery-result": DiscoveryResult,
    "trace-summary": TraceSummary,
    "claim-provenance": ClaimProvenance,
    "run-progress": RunProgress,
    "discovery-view": DiscoveryView,
    "doctor-report": DoctorReport,
    "run-trace": RunTrace,
    "run-summary": RunSummary,
    "pack-summary": PackSummary,
    "bench-report": BenchReport,
}

# Written by Corelata and read by others: computed fields (BenchReport's `Rate.ratio`) belong in
# the schema, which only serialization mode includes. Everything else is validated on input.
SERIALIZED: frozenset[str] = frozenset({"bench-report"})


def export(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in EXPORTED.items():
        path = out_dir / f"{name}.schema.json"
        mode = "serialization" if name in SERIALIZED else "validation"
        schema = model.model_json_schema(mode=mode)
        text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)
        path.write_text(text + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out_dir = Path(args[0]) if args else Path("../schema")
    for path in export(out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

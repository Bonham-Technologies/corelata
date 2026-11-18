"""The terminal rendering of a `BenchReport`."""

from corelata.bench.schema import BenchReport, Rate, RunResult

# The outcome column fits "gate_rejected" or "completed findings_open"; an errored run's error
# is cut to it, so the columns after it stay aligned (R-M13-4); bench.json keeps it whole.
OUTCOME_WIDTH = 24
# The gate column fits "rejected · insufficient"; when the gate disagreed with the scenario its
# first reason follows the row, cut to GATE_REASON_CHARS (R-M12-6).
GATE_WIDTH = 23
GATE_REASON_CHARS = 60


def _pct(rate: Rate) -> str:
    if rate.total == 0:
        return "n/a"
    return f"{rate.agree}/{rate.total} ({round(100 * rate.agree / rate.total)}%)"


def _cut(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _outcome(run: RunResult) -> tuple[str, str]:
    """The `agree` flag and the `outcome` text of a table row."""
    if not run.ok:
        return "err", _cut(run.error or "", OUTCOME_WIDTH)
    state = run.state.value if run.state is not None else "?"
    status = f" {run.status.value}" if run.status is not None else ""
    return ("yes" if run.agree else "no"), f"{state}{status}"


def _gate(run: RunResult) -> tuple[str, str]:
    """The `gate` column and, when the gate disagreed with the scenario, its first reason."""
    if run.gate is None:
        return "-", ""
    verdict = "supported" if run.gate.supported else "rejected"
    column = f"{verdict} · {run.gate.substance.value}"
    if run.gate_agree is False and run.gate.reasons:
        return column, _cut(run.gate.reasons[0], GATE_REASON_CHARS)
    return column, ""


def _models(models: dict[str, str]) -> list[str]:
    """One line per model id with the roles it serves, in role order."""
    roles: dict[str, list[str]] = {}
    for role, model in models.items():
        roles.setdefault(model, []).append(role)
    width = max((len(m) for m in roles), default=0)
    return ["models:", *(f"  {m:<{width}}  {', '.join(rs)}" for m, rs in roles.items())]


def format_bench(report: BenchReport) -> str:
    s = report.summary
    width = max([len(x.name) for x in report.scenarios] + [8])
    lines = [
        f"corelata bench {report.corelata_version}  config {report.config_hash}  "
        f"{report.started_at:%Y-%m-%d %H:%M} UTC",
        *_models(report.models),
        f"scenarios: {report.scenarios_dir} (repeat {report.repeat})",
        "",
        f"{'scenario':<{width}}  {'run':>3}  {'agree':<5}  {'outcome':<{OUTCOME_WIDTH}} "
        f"{'gate':<{GATE_WIDTH}}  {'time':>7}  {'calls':>5}  {'tokens':>6}",
    ]
    for scenario in report.scenarios:
        for run in scenario.runs:
            agree, outcome = _outcome(run)
            gate, reason = _gate(run)
            row = (
                f"{scenario.name:<{width}}  {run.repeat:>3}  {agree:<5}  "
                f"{outcome:<{OUTCOME_WIDTH}} {gate:<{GATE_WIDTH}}  {run.duration_s:>6.1f}s  "
                f"{run.calls:>5}  "
                f"{run.tokens_in + run.tokens_out:>6}"
            )
            lines.append(f"{row}  {reason}" if reason else row)
    lines += [
        "",
        f"full agreement {_pct(s.full_agreement)}",
        f"gate agreement {_pct(s.gate_agreement)}",
        f"rule-failure agreement {_pct(s.rule_agreement)}",
        f"state agreement {_pct(s.state_agreement)}",
        f"runs {s.runs}, errors {s.errors}, tokens in {s.tokens_in}, out {s.tokens_out}, "
        f"{s.duration_s:.1f}s",
    ]
    noisy = {rid: t for rid, t in report.rules.items() if t.missed or t.unexpected}
    if noisy:
        lines += ["", "rules with misses or unexpected failures"]
        for rid, t in noisy.items():
            lines.append(
                f"  {rid}: expected {t.expected}, hit {t.hit}, missed {t.missed}, "
                f"unexpected {t.unexpected}"
            )
    mismatched = [
        (sc.name, run) for sc in report.scenarios for run in sc.runs if run.ok and run.mismatches
    ]
    if mismatched:
        lines += ["", "mismatches"]
        for name, run in mismatched:
            lines.append(f"  {name} run {run.repeat}:")
            lines += [f"    {m}" for m in run.mismatches]
    errored = [(sc.name, run) for sc in report.scenarios for run in sc.runs if not run.ok]
    if errored:  # the table cuts an error to its column (R-M13-4); here it is whole (R-M13-9)
        lines += ["", "errors"]
        lines += [
            f"  {name} run {run.repeat}: {' '.join((run.error or '').split())}"
            for name, run in errored
        ]
    return "\n".join(lines) + "\n"

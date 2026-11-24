"""Command-line interface (spec §10.2).

Exit codes: 0 completed clean, 3 completed with findings open (run, check), disagreement
(bench) or difference (pack diff),
4 gate rejected, 1 failed, 2 usage or config error, 130 interrupted."""

import argparse
import asyncio
import contextlib
import json
import re
import secrets
import sys
from pathlib import Path

from pydantic import ValidationError

from corelata.bench import scenarios_path
from corelata.bench.run import exit_code as bench_exit_code
from corelata.bench.run import run_bench
from corelata.bench.text import format_bench
from corelata.cli_ops import COMMANDS, add_commands, run_command
from corelata.config import ConfigError, CorelataConfig, default_config_path, load_config
from corelata.exports import (
    REPORT_FORMATS,
    DocxExportError,
    dump_json,
    render_outputs,
    write_outputs,
)
from corelata.ingest.base import IngestError
from corelata.ingest.coglossa import load_coglossa_export
from corelata.ingest.ocr import OcrSettings
from corelata.ingest.units import make_source
from corelata.llm.agent import AGENT_FAILURES, CallLog
from corelata.llm.registry import build_backends
from corelata.pipeline import (
    RunOptions,
    discover,
    load_run_pack,
    run_check,
    run_report,
    utcnow,
)
from corelata.profiler import extract_profile, profile_yaml, read_examples
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.render.docx import RenderError
from corelata.scenarios import ScenarioError, load_scenarios
from corelata.schema import ReportStatus, RunRecord, RunState, Source
from corelata.service import InvalidRequestError, check_run_text
from corelata.stages.structure import REPORT_ID
from corelata.standards.diff import diff_packs, format_diff
from corelata.standards.loader import PackError, chain_profiles, load_pack, validate_pack
from corelata.standards.schema import ResolvedPack
from corelata.testing.fake_openai import FakeOpenAIServer
from corelata.trace import (
    TraceError,
    claim_provenance,
    format_summary,
    load_record,
    summarize,
)
from corelata.version import version_line

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_FINDINGS_OPEN, EXIT_GATE_REJECTED = 0, 1, 2, 3, 4
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corelata", description="Standards-enforced intelligence report production."
    )
    parser.add_argument("--version", action="version", version=version_line())
    sub = parser.add_subparsers(dest="command", required=True)

    def inputs(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "inputs", nargs="*", type=Path, help="TXT, MD, DOCX, HTML, PDF, JSON or CSV files"
        )
        p.add_argument(
            "--coglossa-export",
            action="append",
            default=[],
            type=Path,
            help="a Coglossa run export (JSON); repeatable",
        )
        p.add_argument("--config", type=Path, default=default_config_path())

    run = sub.add_parser("run", help="produce a report from sources and a value statement")
    inputs(run)
    run.add_argument("--statement", help="the analyst's value statement")
    run.add_argument("--statement-file", type=Path, help="file holding the value statement")
    run.add_argument("--profile", help="standards pack profile (team overlay)")
    run.add_argument("--max-iterations", type=int, help="audit loop bound (default from config)")
    run.add_argument("--guidance", default="", help="extra guidance for the writer")
    run.add_argument("--out", type=Path, help="output directory (default corelata-out/<run_id>)")
    run.add_argument(
        "--claim-ids", action="store_true", help="show claim ids in report.md and report.html"
    )

    run.add_argument(
        "--project", help="queue the run in this project instead of executing it here (database)"
    )
    run.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="an already ingested source to include (with --project; repeatable)",
    )
    run.add_argument("--parent-run", help="the run this one reruns (with --project)")

    chk = sub.add_parser(
        "check", help="audit a finished report against the standards pack without rewriting it"
    )
    chk.add_argument("report", type=Path, help="the report to check: DOCX, MD, HTML, PDF or TXT")
    chk.add_argument(
        "inputs", nargs="*", type=Path, help="its sources: TXT, MD, DOCX, HTML, PDF, JSON or CSV"
    )
    chk.add_argument(
        "--coglossa-export",
        action="append",
        default=[],
        type=Path,
        help="a Coglossa run export (JSON) among its sources; repeatable",
    )
    chk.add_argument("--config", type=Path, default=default_config_path())
    chk.add_argument("--pack", help="standards pack (default: standards.default_pack)")
    chk.add_argument("--profile", help="standards pack profile (team overlay)")
    chk.add_argument("--statement", help="what the report set out to establish (optional)")
    chk.add_argument("--statement-file", type=Path, help="file holding that statement")
    chk.add_argument("--out", type=Path, help="output directory (default corelata-out/<run_id>)")
    chk.add_argument(
        "--claim-ids", action="store_true", help="show claim ids in report.md and report.html"
    )

    disc = sub.add_parser("discover", help="propose value statements for the sources")
    inputs(disc)
    disc.add_argument("--audience", default="", help="who the report is for, if known")
    disc.add_argument(
        "--project", help="queue the discovery in this project instead of running it here"
    )
    disc.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="an already ingested source to include (with --project; repeatable)",
    )

    rep = sub.add_parser("report", help="re-render a finished run's report from its directory")
    rep.add_argument("run_dir", type=Path, help="a directory written by `corelata run`")
    rep.add_argument("--format", choices=REPORT_FORMATS, default="md")
    rep.add_argument("--claim-ids", action="store_true", help="show claim ids (md, html, docx)")
    rep.add_argument("--out", type=Path, help="write here instead of stdout (required for docx)")
    rep.add_argument(
        "--docx-reference", type=Path, help="reference .docx for styles (else the neutral built-in)"
    )

    tr = sub.add_parser("trace", help="summarise a run from its directory")
    tr.add_argument("run_dir", type=Path, help="a directory written by `corelata run`")
    tr.add_argument("--json", action="store_true", help="machine-readable output")
    tr.add_argument("--claim", help="show one claim's evidence units instead of the summary")

    pack = sub.add_parser("pack", help="inspect standards packs")
    pack_sub = pack.add_subparsers(dest="pack_command", required=True)
    for name, help_ in (
        ("validate", "check a pack directory or name"),
        ("show", "print the resolved pack"),
    ):
        p = pack_sub.add_parser(name, help=help_)
        p.add_argument("name", help="pack name, or a directory for validate")
        p.add_argument("--profile")
        p.add_argument("--packs-dir", type=Path)
        p.add_argument("--config", type=Path)
    d = pack_sub.add_parser("diff", help="compare two packs, profiles or run snapshots")
    for side in ("left", "right"):
        d.add_argument(
            side,
            help="a pack name, a pack directory, or a run directory / trace.json (its snapshot)",
        )
    d.add_argument("--profile-left", help="profile to apply to the left pack name")
    d.add_argument("--profile-right", help="profile to apply to the right pack name")
    d.add_argument("--packs-dir", type=Path)
    d.add_argument("--config", type=Path)
    d.add_argument("--json", action="store_true", help="print the diff as JSON")

    profile = sub.add_parser("profile", help="team profiles")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    ext = profile_sub.add_parser("extract", help="draft a team profile from example reports")
    ext.add_argument(
        "--from", dest="from_dir", type=Path, required=True, help="directory of example reports"
    )
    ext.add_argument("--out", type=Path, required=True, help="profile YAML to write")
    ext.add_argument("--name", help="profile name (default: the --out file's stem)")
    ext.add_argument("--extends", help="pack to extend (default: standards.default_pack)")
    ext.add_argument("--packs-dir", type=Path, help="default: standards.packs_dir")
    ext.add_argument(
        "--budget-tokens",
        type=int,
        help="passages budget across all reports (default: pipeline.writer_unit_budget_tokens)",
    )
    ext.add_argument("--force", action="store_true", help="overwrite an existing --out")
    ext.add_argument("--config", type=Path, default=default_config_path())

    fake = sub.add_parser("fake-openai", help="serve a synthetic OpenAI-compatible endpoint")
    fake.add_argument("--host", default="127.0.0.1")
    fake.add_argument("--port", type=int, default=8000)
    fake.add_argument("--model", action="append", dest="models")
    fake.add_argument(
        "--needs-repair",
        action="store_true",
        help="answer the first turn of every structured call with '{}', so each call needs its "
        "repair turn (a model doctor warns about)",
    )
    bench = sub.add_parser(
        "bench", help="play the scenario set against the configured models and report agreement"
    )
    bench.add_argument("--config", type=Path, default=default_config_path())
    bench.add_argument(
        "--scenarios",
        type=scenarios_path,
        default="synthetic",
        help="'synthetic' (the default; the set CI runs), 'real' (written for real models) or a "
        "directory of scenario YAML files",
    )
    bench.add_argument(
        "--only", action="append", default=[], metavar="NAME", help="run only this scenario"
    )
    bench.add_argument("--repeat", type=int, default=1, help="runs per scenario (1-20)")
    bench.add_argument(
        "--concurrency", type=int, default=1, help="scenario runs in flight at once (1-16)"
    )
    bench.add_argument(
        "--store-io", action="store_true", help="keep model requests and responses in the traces"
    )
    bench.add_argument("--out", type=Path, help="write bench.json and each run's trace here")
    bench.add_argument("--json", action="store_true", help="print the report as JSON")
    add_commands(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in COMMANDS:
            return run_command(args)
        if args.command == "run":
            return _run(args)
        if args.command == "discover":
            return _discover(args)
        if args.command == "check":
            return _check(args)
        if args.command == "pack":
            return _pack(args)
        if args.command == "profile":
            return _profile(args)
        if args.command == "bench":
            return _bench(args)
        if args.command == "report":
            return _report(args)
        if args.command == "trace":
            return _trace(args)
        return _fake_openai(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


def _usage(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return EXIT_USAGE


def load_sources(
    paths: list[Path], coglossa_exports: list[Path], ocr: OcrSettings | None = None
) -> list[Source]:
    sources: list[Source] = []
    for path in paths:
        sources.append(make_source(f"src{len(sources) + 1}", path, ocr=ocr))
    for path in coglossa_exports:
        sources.extend(load_coglossa_export(f"src{len(sources) + 1}", path))
    return sources


def _setup(args: argparse.Namespace) -> tuple[CorelataConfig, list[Source], PromptLibrary]:
    cfg, issues = load_config(args.config)
    for issue in issues:
        print(f"{issue.level}: {issue.message}", file=sys.stderr)
    prompts = PromptLibrary(cfg.prompts_dir)
    validate_prompts(cfg, prompts)
    if not args.inputs and not args.coglossa_export:
        raise IngestError("give at least one input file or --coglossa-export")
    return cfg, load_sources(args.inputs, args.coglossa_export, cfg.ingest.ocr_settings()), prompts


def _statement(args: argparse.Namespace) -> str:
    if bool(args.statement) == bool(args.statement_file):
        raise ConfigError("give exactly one of --statement or --statement-file")
    text = args.statement if args.statement else args.statement_file.read_text(encoding="utf-8")
    if not text.strip():
        raise ConfigError("the value statement is empty")
    return text.strip()


def _run(args: argparse.Namespace) -> int:
    try:
        statement = _statement(args)
        check_run_text(statement, args.guidance)
    except (ConfigError, InvalidRequestError, OSError) as e:
        return _usage(str(e))
    if args.source_id and args.project is None:
        return _usage("--source-id needs --project")
    if args.parent_run and args.project is None:
        return _usage("--parent-run needs --project")
    if args.project is not None:
        args.value_statement = statement
        return run_command(args, "queue-run")
    try:
        cfg, sources, prompts = _setup(args)
        pack = load_run_pack(cfg, args.profile)
    except (ConfigError, IngestError, PackError, OSError) as e:
        return _usage(str(e))
    run_id = secrets.token_hex(6)
    out_dir = args.out or Path("corelata-out") / run_id
    try:
        if out_dir.exists() and not out_dir.is_dir():
            raise NotADirectoryError("not a directory")
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _usage(f"cannot write to {out_dir}: {e.strerror or e}")
    backends = build_backends(cfg)
    log = CallLog(store_io=cfg.audit.store_llm_io)
    options = RunOptions(
        run_id=run_id,
        value_statement=statement,
        profile=args.profile,
        max_iterations=args.max_iterations,
        extra_guidance=args.guidance,
    )

    async def go() -> RunRecord:
        try:
            return await run_report(
                cfg, sources, options, backends=backends, prompts=prompts, log=log, pack=pack
            )
        finally:
            for b in backends.values():
                await b.aclose()

    try:
        record = asyncio.run(go())
    except ValueError as e:
        return _usage(str(e))
    try:
        write_outputs(out_dir, record, pack, args.claim_ids)
    except DocxExportError as e:
        print(
            f"run {record.run_id}: completed {record.status.value} after {record.iterations} "
            f"revision(s), but the DOCX export failed: {e} -> {out_dir}",
            file=sys.stderr,
        )
        return EXIT_FAILED
    if record.state is RunState.GATE_REJECTED:
        reasons = "; ".join(record.gate.reasons) if record.gate else ""
        print(f"run {record.run_id}: gate rejected ({reasons}) -> {out_dir}")
        return EXIT_GATE_REJECTED
    if record.state is RunState.FAILED:
        print(f"run {record.run_id}: failed: {record.error} -> {out_dir}")
        return EXIT_FAILED
    print(
        f"run {record.run_id}: completed {record.status.value} after {record.iterations} "
        f"revision(s), {record.usage.calls} model calls -> {out_dir}"
    )
    assert record.report is not None  # a completed run always has one
    for note in record.report.metadata.degradations:
        print(f"run {record.run_id}: {note}", file=sys.stderr)
    return EXIT_FINDINGS_OPEN if record.status is ReportStatus.FINDINGS_OPEN else EXIT_OK


def _check(args: argparse.Namespace) -> int:
    """`corelata check` (CRL-94): audit a finished report against the pack, in-process. Exit 0
    when every rule passes, 3 with findings open, 1 failed, 2 usage."""
    try:
        statement = ""
        if args.statement or args.statement_file:
            statement = _statement(args)
        check_run_text(statement, "")
        cfg, issues = load_config(args.config)
        for issue in issues:
            print(f"{issue.level}: {issue.message}", file=sys.stderr)
        prompts = PromptLibrary(cfg.prompts_dir)
        validate_prompts(cfg, prompts)
        if not args.inputs and not args.coglossa_export:
            raise IngestError("give the report and at least one source file or --coglossa-export")
        ocr = cfg.ingest.ocr_settings()
        report = make_source(REPORT_ID, args.report, ocr=ocr)
        sources = load_sources(args.inputs, args.coglossa_export, ocr)
        pack = load_pack(
            args.pack or cfg.standards.default_pack,
            packs_dir=cfg.standards.packs_dir,
            profile=args.profile or cfg.standards.default_profile,
        )
    except (ConfigError, InvalidRequestError, IngestError, PackError, OSError) as e:
        return _usage(str(e))
    run_id = secrets.token_hex(6)
    out_dir = args.out or Path("corelata-out") / run_id
    try:
        if out_dir.exists() and not out_dir.is_dir():
            raise NotADirectoryError("not a directory")
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _usage(f"cannot write to {out_dir}: {e.strerror or e}")
    backends = build_backends(cfg)
    log = CallLog(store_io=cfg.audit.store_llm_io)
    options = RunOptions(run_id=run_id, value_statement=statement, profile=args.profile)
    llm = {"backends": backends, "prompts": prompts, "log": log}

    async def go() -> RunRecord:
        try:
            return await run_check(cfg, sources, report, options, pack=pack, **llm)
        finally:
            for b in backends.values():
                await b.aclose()

    record = asyncio.run(go())
    try:
        write_outputs(out_dir, record, pack, args.claim_ids)
    except DocxExportError as e:
        print(f"check {record.run_id}: the DOCX export failed: {e} -> {out_dir}", file=sys.stderr)
        return EXIT_FAILED
    if record.state is not RunState.COMPLETED:
        print(f"check {record.run_id}: {record.state.value}: {record.error} -> {out_dir}")
        return EXIT_FAILED
    assert record.report is not None
    failed = len(record.report.metadata.open_findings)
    print(
        f"check {record.run_id}: checked {record.status.value}, {failed} finding"
        f"{'' if failed == 1 else 's'} open, {len(record.report.claims)} claims, "
        f"{len(record.report.unsourced_claims())} unsourced -> {out_dir}"
    )
    for note in record.report.metadata.degradations:
        print(f"check {record.run_id}: {note}", file=sys.stderr)
    return EXIT_FINDINGS_OPEN if record.status is ReportStatus.FINDINGS_OPEN else EXIT_OK


def _discover(args: argparse.Namespace) -> int:
    if args.source_id and args.project is None:
        return _usage("--source-id needs --project")
    if args.project is not None:
        return run_command(args, "queue-discover")
    try:
        cfg, sources, prompts = _setup(args)
    except (ConfigError, IngestError, PackError, OSError) as e:
        return _usage(str(e))
    backends = build_backends(cfg)

    async def go():
        try:
            return await discover(
                cfg,
                sources,
                backends=backends,
                prompts=prompts,
                log=CallLog(),
                audience_hint=args.audience,
            )
        finally:
            for b in backends.values():
                await b.aclose()

    try:
        result = asyncio.run(go())
    except Exception as e:  # noqa: BLE001 - the CLI reports any model failure as exit 1
        print(f"discovery failed: {e}", file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return EXIT_OK


def _load_run(run_dir: Path) -> tuple[RunRecord, ResolvedPack]:
    record = load_record(run_dir)
    try:
        return record, ResolvedPack.model_validate(record.pack_snapshot)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "(top level)"
        raise TraceError(
            f"{run_dir}: pack_snapshot is not a resolved pack ({where}: {first['msg']})"
        ) from e


def _report(args: argparse.Namespace) -> int:
    try:
        record, pack = _load_run(args.run_dir)
    except TraceError as e:
        return _usage(str(e))
    if record.report is None:
        return _usage(f"run {record.run_id} has no report (state {record.state.value})")
    if args.format == "docx" and args.out is None:
        return _usage("--format docx needs --out FILE")
    reference = args.docx_reference
    if reference is None and (args.run_dir / "reference.docx").is_file():
        reference = args.run_dir / "reference.docx"
    if args.format == "docx" and reference is None and pack.format.docx_reference is not None:
        print(
            f"note: the run's profile names docx_reference '{pack.format.docx_reference}', which "
            "a run directory cannot locate; rendering with the neutral template. Pass "
            "--docx-reference FILE to use it.",
            file=sys.stderr,
        )
    try:
        outputs = render_outputs(
            record,
            pack,
            with_claim_ids=args.claim_ids,
            docx_claim_ids=args.claim_ids,
            docx_reference=reference,
            formats=(args.format,),
        )
    except RenderError as e:
        return _usage(str(e))
    content = outputs[f"report.{args.format}"]
    if args.out is None:
        sys.stdout.write(content)  # text formats only; docx was refused above
        return EXIT_OK
    try:
        if isinstance(content, bytes):
            args.out.write_bytes(content)
        else:
            args.out.write_text(content, encoding="utf-8")
    except OSError as e:
        return _usage(f"cannot write {args.out}: {e.strerror or e}")
    return EXIT_OK


def _trace(args: argparse.Namespace) -> int:
    try:
        record = load_record(args.run_dir)
        if args.claim is not None:
            prov = claim_provenance(record, args.claim)
            if args.json:
                print(dump_json(prov.model_dump(mode="json")), end="")
                return EXIT_OK
            print(f"{prov.claim.id} ({prov.claim.kind.value}): {prov.claim.text}")
            if prov.claim.likelihood_term:
                print(f"likelihood: {prov.claim.likelihood_term}")
            for e in prov.evidence:
                print(f"  {e.ref}  {e.source_name}, {e.locator}")
                print(f"    {e.text}")
            if not prov.evidence:
                print("  (no evidence)")
            print(f"cited by: {', '.join(prov.cited_by) or 'nothing'}")
            return EXIT_OK
    except TraceError as e:
        return _usage(str(e))
    summary = summarize(record)
    if args.json:
        print(dump_json(summary.model_dump(mode="json")), end="")
    else:
        degraded = record.report.metadata.degradations if record.report else []
        print(format_summary(summary, degraded), end="")
    return EXIT_OK


def _packs_dir(args: argparse.Namespace) -> Path | None:
    if args.packs_dir is not None:
        return args.packs_dir
    if args.config is not None:
        cfg, _ = load_config(args.config)
        return cfg.standards.packs_dir
    return None


def _pack(args: argparse.Namespace) -> int:
    try:
        packs_dir = _packs_dir(args)
    except ConfigError as e:
        return _usage(str(e))
    if args.pack_command == "validate":
        issues = validate_pack(args.name, packs_dir=packs_dir)
        for issue in issues:
            print(f"{issue.level}: {issue.message}")
        if not issues:
            print("ok")
        return EXIT_FAILED if any(i.level == "error" for i in issues) else EXIT_OK
    if args.pack_command == "diff":
        return _pack_diff(args, packs_dir)
    try:
        pack = load_pack(args.name, packs_dir=packs_dir, profile=args.profile, allow_draft=True)
    except PackError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(pack.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return EXIT_OK


def _pack_side(spec: str, profile: str | None, packs_dir: Path | None) -> ResolvedPack:
    """A pack name (with an optional profile), a pack directory, or a run directory / trace.json
    whose snapshot is the pack a run actually used (spec §6.6)."""
    path = Path(spec)
    run_dir = path.parent if path.is_file() and path.name == "trace.json" else path
    if (run_dir / "trace.json").is_file():
        if profile is not None:
            raise ConfigError(f"{spec} is a run snapshot; it carries its own profile")
        return _load_run(run_dir)[1]
    if (path / "pack.yaml").is_file():
        return load_pack(path.name, packs_dir=path.parent, profile=profile, allow_draft=True)
    return load_pack(spec, packs_dir=packs_dir, profile=profile, allow_draft=True)


def _pack_diff(args: argparse.Namespace, packs_dir: Path | None) -> int:
    try:
        left = _pack_side(args.left, args.profile_left, packs_dir)
        right = _pack_side(args.right, args.profile_right, packs_dir)
    except ConfigError as e:
        return _usage(str(e))
    except (PackError, TraceError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAILED
    diff = diff_packs(left, right, left_name=args.left, right_name=args.right)
    if args.json:
        print(dump_json(diff.model_dump(mode="json")), end="")
    else:
        print(format_diff(diff, left=left, right=right), end="")
    return EXIT_OK if diff.empty else EXIT_FINDINGS_OPEN


_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _profile(args: argparse.Namespace) -> int:
    name = args.name or args.out.stem
    if not _PROFILE_NAME.match(name):
        return _usage(
            f"--name '{name}' must match {_PROFILE_NAME.pattern} (lowercase, digits, dashes)"
        )
    if args.out.is_dir():
        return _usage(f"--out {args.out} is a directory")
    if args.out.exists() and not args.force:
        return _usage(f"{args.out} exists; pass --force to overwrite it")
    if not args.out.parent.is_dir():
        return _usage(f"the directory of --out does not exist: {args.out.parent}")
    if args.budget_tokens is not None and args.budget_tokens < 1:
        return _usage("--budget-tokens must be at least 1")
    try:
        cfg, issues = load_config(args.config)
        for issue in issues:
            print(f"{issue.level}: {issue.message}", file=sys.stderr)
        prompts = PromptLibrary(cfg.prompts_dir)
        validate_prompts(cfg, prompts)
        if cfg.roles.profiler is None:
            raise ConfigError(
                "roles.profiler is not configured; add `profiler: {model: <key>}` under roles"
            )
        model = cfg.models[cfg.roles.model_for("profiler")]
        examples = read_examples(
            args.from_dir,
            budget_tokens=args.budget_tokens
            or min(cfg.pipeline.writer_unit_budget_tokens, model.context_window // 2),
            bytes_per_token=model.bytes_per_token,
        )
        extends = args.extends or cfg.standards.default_pack
        packs_dir = args.packs_dir if args.packs_dir is not None else cfg.standards.packs_dir
        owners = chain_profiles(extends, packs_dir)
        if name in owners:
            print(
                f"warning: profile '{name}' already exists in pack '{owners[name]}'; a profile "
                "file of that name in its profiles/ directory would replace it",
                file=sys.stderr,
            )
        backends = build_backends(cfg)
    except (ConfigError, IngestError, PackError, OSError) as e:
        return _usage(str(e))
    log = CallLog(store_io=False)

    async def go():
        try:
            return await extract_profile(
                cfg,
                backends=backends,
                prompts=prompts,
                log=log,
                examples=examples,
                name=name,
                extends=extends,
                packs_dir=packs_dir,
            )
        finally:
            for backend in backends.values():
                await backend.aclose()

    try:
        extraction = asyncio.run(go())
    except PackError as e:
        return _usage(str(e))
    except AGENT_FAILURES as e:
        print(
            "error: the profiler could not produce a valid draft "
            f"(try a smaller --budget-tokens if the model's context is small): {e}",
            file=sys.stderr,
        )
        return EXIT_FAILED
    try:
        text = profile_yaml(extraction, written_at=utcnow())
    except ValueError as e:  # the round-trip guard: a bug in the extractor, not the operator
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAILED
    try:
        if args.force:
            args.out.write_text(text, encoding="utf-8")
        else:  # "x": never replace a file that appeared since the early check
            with open(args.out, "x", encoding="utf-8") as f:
                f.write(text)
    except FileExistsError:
        print(f"error: {args.out} exists; pass --force", file=sys.stderr)
        print(text, end="")
        return EXIT_USAGE
    except OSError as e:
        print(f"error: cannot write {args.out}: {e}", file=sys.stderr)
        print(text, end="")
        return EXIT_FAILED
    print(
        f"wrote {args.out} (draft profile '{name}' extends '{extends}'; "
        f"{len(extraction.observations)} observations)"
    )
    for observation in extraction.observations:
        print(f"  - {observation}")
    return EXIT_OK


def _bench(args: argparse.Namespace) -> int:
    if not 1 <= args.repeat <= 20:
        return _usage("--repeat must be between 1 and 20")
    if not 1 <= args.concurrency <= 16:
        return _usage("--concurrency must be between 1 and 16")
    if args.out is not None and args.out.exists() and not args.out.is_dir():
        return _usage(f"--out {args.out} is not a directory")
    try:
        cfg, issues = load_config(args.config)
        for issue in issues:
            print(f"{issue.level}: {issue.message}", file=sys.stderr)
        prompts = PromptLibrary(cfg.prompts_dir)
        validate_prompts(cfg, prompts)
        scenarios = load_scenarios(args.scenarios)
    except (ConfigError, ScenarioError, OSError) as e:
        return _usage(str(e))
    if not scenarios:
        return _usage(f"no scenarios in {args.scenarios}")
    if args.only:
        only = set(args.only)
        known = {s.name for s in scenarios}
        for name in args.only:
            if name not in known:
                return _usage(f"unknown scenario '{name}' (have: {', '.join(sorted(known))})")
        scenarios = [s for s in scenarios if s.name in only]
    try:
        if args.out is not None:
            args.out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _usage(f"--out {args.out}: {e}")
    try:
        backends = build_backends(cfg)
    except ConfigError as e:
        return _usage(str(e))

    async def go():
        try:
            return await run_bench(
                cfg,
                scenarios,
                backends=backends,
                prompts=prompts,
                repeat=args.repeat,
                concurrency=args.concurrency,
                store_io=args.store_io,
                out_dir=args.out,
                scenarios_dir=args.scenarios,
                progress=lambda line: print(line, file=sys.stderr, flush=True),
            )
        finally:
            for backend in backends.values():
                await backend.aclose()

    try:
        report = asyncio.run(go())
    except KeyboardInterrupt:
        where = f"; the partial report is {args.out / 'bench.json'}" if args.out is not None else ""
        print(f"interrupted{where}", file=sys.stderr)
        return EXIT_INTERRUPTED
    if args.json:
        print(dump_json(report.model_dump(mode="json")), end="")
    else:
        print(format_bench(report), end="")
    return bench_exit_code(report)


def _fake_openai(args: argparse.Namespace) -> int:
    models = tuple(args.models or ["fake-model"])
    server = FakeOpenAIServer(
        args.host, args.port, models, keep_requests=False, needs_repair=args.needs_repair
    )
    print(f"fake OpenAI-compatible server at {server.base_url} (Ctrl+C to stop)", flush=True)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
    finally:
        server.stop()
    return EXIT_OK

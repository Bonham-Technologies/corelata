"""CLI commands for the queued deployment (spec §10.2): `migrate`, `worker`, and (Tasks 9 and
10) the run lifecycle and `doctor`. They talk to Postgres; `corelata run FILES` without
`--project` needs none of them."""

import argparse
import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from corelata import removal, service
from corelata.config import ConfigError, CorelataConfig, default_config_path, load_config
from corelata.exports import DocxExportError, dump_json, write_outputs
from corelata.ingest.base import IngestError
from corelata.ingest.ocr import OcrSettings
from corelata.logs import configure_json_logging, remove_json_logging
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.schema import TERMINAL_STATES, DiscoveryView, ReviewAction, RunProgress
from corelata.service import QueueUnavailableError
from corelata.standards.loader import PackError
from corelata.standards.schema import ResolvedPack
from corelata.storage import Storage, StorageError, build_storage
from corelata.store import runs
from corelata.store.db import Database, database_url, error_reason, redact
from corelata.store.migrate import (
    DatabaseUnavailable,
    connect_error,
    ensure_migrated,
    migration_state,
    upgrade,
)
from corelata.store.runs import NotFoundError
from corelata.worker.app import ProcrastinateQueue, open_app, run_worker
from corelata.worker.execute import DB_ERRORS

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
USER_ERRORS = (
    ConfigError,
    IngestError,
    PackError,
    StorageError,
    NotFoundError,
    service.ConflictError,
    service.InvalidRequestError,
    OSError,
)


def _config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=default_config_path())


def add_commands(sub: argparse._SubParsersAction) -> None:
    _config_arg(sub.add_parser("migrate", help="create or upgrade the database schema"))
    worker = sub.add_parser("worker", help="process queued runs and discoveries")
    _config_arg(worker)
    worker.add_argument("--burst", action="store_true", help="exit when the queue is empty")

    ingest = sub.add_parser("ingest", help="add source files to a project (database)")
    _config_arg(ingest)
    ingest.add_argument("inputs", nargs="*", type=Path)
    ingest.add_argument("--coglossa-export", action="append", default=[], type=Path)
    ingest.add_argument("--project", required=True)

    status = sub.add_parser("status", help="show a queued run or discovery")
    _config_arg(status)
    status.add_argument("id")
    status.add_argument("--json", action="store_true")

    cancel = sub.add_parser("cancel", help="cancel a queued or running run")
    _config_arg(cancel)
    cancel.add_argument("run_id")

    review = sub.add_parser("review", help="accept a completed run, or return it with a note")
    _config_arg(review)
    review.add_argument("run_id")
    action = review.add_mutually_exclusive_group(required=True)
    action.add_argument("--accept", dest="action", action="store_const", const="accept")
    action.add_argument("--return", dest="action", action="store_const", const="return")
    review.add_argument("--note", default="", help="guidance for the writer (required for return)")
    review.add_argument("--actor", help="who reviewed")

    export = sub.add_parser(
        "export", help="write a run directory (trace and exports) from the database"
    )
    _config_arg(export)
    export.add_argument("run_id")
    export.add_argument("--out", type=Path, required=True)

    sources = sub.add_parser("sources", help="list a project's sources with their ids")
    _config_arg(sources)
    sources.add_argument("--project", required=True)

    delete_source = sub.add_parser(
        "delete-source", help="delete a source added by mistake (operators; cannot be undone)"
    )
    _config_arg(delete_source)
    delete_source.add_argument("source_id")
    delete_source.add_argument(
        "--with-runs",
        action="store_true",
        help="also delete the runs that used it, with their reports and traces",
    )
    delete_source.add_argument("--yes", action="store_true", help="do not ask to confirm")

    delete_project = sub.add_parser(
        "delete-project",
        help="delete a project and everything in it (operators; cannot be undone)",
    )
    _config_arg(delete_project)
    delete_project.add_argument("project", help="the project's name")
    delete_project.add_argument("--yes", action="store_true", help="do not ask to confirm")

    doctor = sub.add_parser("doctor", help="check the installation")
    _config_arg(doctor)
    doctor.add_argument("--json", action="store_true", help="print the result as JSON")
    doctor.add_argument("--no-probe", action="store_true", help="skip the test completions")


def _load(args: argparse.Namespace) -> CorelataConfig:
    cfg, warnings = load_config(args.config)
    for warning in warnings:
        print(f"{warning.level}: {warning.message}", file=sys.stderr)
    return cfg


def _with_db[T](cfg: CorelataConfig, fn: Callable[[Database], Awaitable[T]]) -> T:
    url = database_url(cfg)
    ensure_migrated(url)  # one clear line instead of a missing-table error

    async def go() -> T:
        db = Database(url)
        try:
            return await fn(db)
        finally:
            await db.dispose()

    return asyncio.run(go())


def _with_queue[T](
    cfg: CorelataConfig, fn: Callable[[Database, service.JobQueue], Awaitable[T]]
) -> T:
    async def go(db: Database) -> T:
        async with open_app(db.url) as opened:
            return await fn(db, ProcrastinateQueue(opened))

    return _with_db(cfg, go)


def _migrate(args: argparse.Namespace) -> int:
    cfg = _load(args)
    url = database_url(cfg)
    try:
        upgrade(url)
    except DB_ERRORS as e:
        raise connect_error(url, e) from e
    print(f"database at {redact(url)} is at revision {migration_state(url).head}")
    return EXIT_OK


def _worker(args: argparse.Namespace) -> int:
    cfg = _load(args)
    handler = configure_json_logging()
    try:
        asyncio.run(run_worker(cfg, burst=args.burst))
    finally:
        remove_json_logging(handler)
    return EXIT_OK


def _id(text: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(text)
    except ValueError:
        raise ConfigError(f"'{text}' is not a {what} id") from None


def _check_readable(path: Path) -> None:
    if not path.is_file():
        raise IngestError(f"input file not found: {path}")
    with path.open("rb") as f:
        f.read(1)


def _read(path: Path) -> bytes:
    if not path.is_file():
        raise IngestError(f"input file not found: {path}")
    return path.read_bytes()


async def _ingest_files(
    db: Database,
    storage,
    project_id: uuid.UUID,
    inputs: list[Path],
    exports: list[Path],
    ocr: OcrSettings | None = None,
) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for path in inputs:
        ids += await service.add_source(db, storage, project_id, path.name, _read(path), ocr=ocr)
    for path in exports:
        ids += await service.add_source(
            db, storage, project_id, path.name, _read(path), coglossa_export=True
        )
    return ids


async def _check_parent(db: Database, parent: uuid.UUID, project_name: str) -> None:
    """Refuse a missing parent run, or one in another project, before anything is created."""
    async with db.session() as s:
        run = await runs.get_run(s, parent)
        project = await runs.get_project(s, run.project_id)
    if project.name != project_name:
        raise service.InvalidRequestError(f"parent run {parent} belongs to another project")


def _ingest(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not args.inputs and not args.coglossa_export:
        raise ConfigError("give at least one input file or --coglossa-export")
    storage = build_storage(cfg.storage)

    async def go(db: Database) -> list[uuid.UUID]:
        pid = await service.create_project(db, args.project)
        return await _ingest_files(
            db, storage, pid, args.inputs, args.coglossa_export, cfg.ingest.ocr_settings()
        )

    for sid in _with_db(cfg, go):
        print(sid)
    return EXIT_OK


def _queue_run(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not args.inputs and not args.coglossa_export and not args.source_id:
        raise ConfigError("give input files, --coglossa-export or --source-id")
    storage = build_storage(cfg.storage)
    prompts = PromptLibrary(cfg.prompts_dir)
    validate_prompts(cfg, prompts)
    parent = _id(args.parent_run, "run") if args.parent_run else None
    source_ids = [_id(s, "source") for s in args.source_id]
    for path in [*args.inputs, *args.coglossa_export]:
        _check_readable(path)

    async def go(db: Database, queue: service.JobQueue) -> uuid.UUID:
        if parent is not None:
            await _check_parent(db, parent, args.project)
        pid = await service.create_project(db, args.project)
        ingested = await _ingest_files(
            db, storage, pid, args.inputs, args.coglossa_export, cfg.ingest.ocr_settings()
        )
        # a file the project has already gives its source back (CRL-126): listed once
        ids = list(dict.fromkeys([*source_ids, *ingested]))
        req = service.RunRequest(
            project_id=pid,
            source_ids=ids,
            value_statement=args.value_statement,
            profile=args.profile,
            max_iterations=args.max_iterations,
            extra_guidance=args.guidance,
            parent_run_id=parent,
        )
        return await service.start_run(db, storage, queue, cfg, prompts, req)

    run_id = _with_queue(cfg, go)
    print(f"run {run_id} queued in project '{args.project}'")
    return EXIT_OK


def _queue_discover(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not args.inputs and not args.coglossa_export and not args.source_id:
        raise ConfigError("give input files, --coglossa-export or --source-id")
    storage = build_storage(cfg.storage)
    source_ids = [_id(s, "source") for s in args.source_id]
    for path in [*args.inputs, *args.coglossa_export]:
        _check_readable(path)

    async def go(db: Database, queue: service.JobQueue) -> uuid.UUID:
        pid = await service.create_project(db, args.project)
        ingested = await _ingest_files(
            db, storage, pid, args.inputs, args.coglossa_export, cfg.ingest.ocr_settings()
        )
        # a file the project has already gives its source back (CRL-126): listed once
        ids = list(dict.fromkeys([*source_ids, *ingested]))
        return await service.start_discovery(db, queue, pid, ids, args.audience)

    did = _with_queue(cfg, go)
    print(f"discovery {did} queued in project '{args.project}'")
    return EXIT_OK


def _show_run(p: RunProgress) -> str:
    status = f" ({p.status.value})" if p.status else ""
    lines = [
        f"run {p.run_id}: {p.state.value}{status}  iteration {p.iteration}/{p.max_iterations}"
        f"  attempts {p.attempts}"
    ]
    if p.parent_run_id:
        lines.append(f"parent: {p.parent_run_id}")
    if p.stages:
        lines.append(
            "stages: "
            + ", ".join(f"{s.stage}@{s.iteration} {'ok' if s.ok else 'failed'}" for s in p.stages)
        )
    if p.usage:
        lines.append(
            f"usage: {p.usage.calls} calls, in {p.usage.tokens_in} tokens, "
            f"out {p.usage.tokens_out} tokens"
        )
    if p.error:
        lines.append(f"error: {p.error}")
    if p.export_error:
        lines.append(f"export error: {p.export_error}")
    if p.worker_gone and p.cancel_requested:
        lines.append("cancel requested, but its worker is gone; cancel it again to end it now")
    elif p.worker_gone:
        lines.append(
            "its worker stopped responding; it starts over when a worker is running again, "
            "or cancel it to end it now"
        )
    elif p.cancel_requested and p.state not in TERMINAL_STATES:
        lines.append("cancel requested; the run stops after the current stage")
    return "\n".join(lines) + "\n"


def _show_discovery(d: DiscoveryView) -> str:
    lines = [f"discovery {d.discovery_id}: {d.state.value}  sources {len(d.source_ids)}"]
    if d.audience_hint:
        lines.append(f"audience hint: {d.audience_hint}")
    for i, c in enumerate(d.candidates, start=1):
        lines.append(f"  {i}. {c.text}")
        lines.append(f"     audience: {c.audience}; evidence: {', '.join(c.evidence) or 'none'}")
        if c.confidence_note:
            lines.append(f"     note: {c.confidence_note}")
    if d.error:
        lines.append(f"error: {d.error}")
    return "\n".join(lines) + "\n"


def _status(args: argparse.Namespace) -> int:
    cfg = _load(args)
    some_id = _id(args.id, "run or discovery")

    async def go(db: Database) -> RunProgress | DiscoveryView:
        try:
            return await service.run_progress(
                db, some_id, stalled_after_s=cfg.worker.stalled_after_s
            )
        except NotFoundError:
            try:
                return await service.get_discovery(
                    db,
                    some_id,
                    deadline_s=cfg.worker.discovery_deadline_s,
                    start_deadline_s=cfg.worker.discovery_start_deadline_s,
                )
            except NotFoundError:
                raise NotFoundError(f"no run or discovery {some_id}") from None

    view = _with_db(cfg, go)
    if args.json:
        print(dump_json(view.model_dump(mode="json")), end="")
    elif isinstance(view, RunProgress):
        print(_show_run(view), end="")
    else:
        print(_show_discovery(view), end="")
    return EXIT_OK


def _cancel(args: argparse.Namespace) -> int:
    cfg = _load(args)
    run_id = _id(args.run_id, "run")
    state = _with_db(
        cfg,
        lambda db: service.cancel_run(db, run_id, stalled_after_s=cfg.worker.stalled_after_s),
    )
    if state in TERMINAL_STATES:
        print(f"run {run_id} cancelled")
    else:
        print(f"run {run_id}: cancel requested; it stops after the current stage")
    return EXIT_OK


def _review(args: argparse.Namespace) -> int:
    cfg = _load(args)
    run_id = _id(args.run_id, "run")
    storage = build_storage(cfg.storage)
    prompts = PromptLibrary(cfg.prompts_dir)
    validate_prompts(cfg, prompts)
    action = ReviewAction(args.action)

    async def go(db: Database, queue: service.JobQueue) -> uuid.UUID | None:
        return await service.review_run(
            db, storage, queue, cfg, prompts, run_id, action, note=args.note, actor=args.actor
        )

    child = _with_queue(cfg, go)
    if action is ReviewAction.ACCEPT:
        print(f"run {run_id} accepted")
    else:
        print(f"run {run_id} returned; new run {child} queued")
    return EXIT_OK


def _export(args: argparse.Namespace) -> int:
    cfg = _load(args)
    run_id = _id(args.run_id, "run")
    storage = build_storage(cfg.storage)

    async def go(db: Database):
        record = await service.get_run_record(db, run_id)
        return record, await service.reference_document(db, storage, run_id)

    record, reference = _with_db(cfg, go)
    pack = ResolvedPack.model_validate(record.pack_snapshot)
    out: Path = args.out
    if out.exists() and not out.is_dir():
        raise ConfigError(f"{out} is not a directory")
    out.mkdir(parents=True, exist_ok=True)
    if reference is not None:
        (out / "reference.docx").write_bytes(reference)
        pack.docx_reference_path = out / "reference.docx"
    write_outputs(out, record, pack, with_claim_ids=False)
    print(f"run {run_id} ({record.state.value}) -> {out}")
    return EXIT_OK


def _sources(args: argparse.Namespace) -> int:
    cfg = _load(args)
    for item in _with_db(cfg, lambda db: removal.list_sources(db, args.project)):
        used = f"used by {item.runs} run{'' if item.runs == 1 else 's'}"
        print(f"{item.id}  {item.created_at:%Y-%m-%d %H:%M}  {used:<16}  {item.name}")
    return EXIT_OK


def _show_removal(r: removal.Removal) -> None:
    print(f"This deletes {removal.summary(r)}:")
    for items, what in zip(r.groups(), ("source", "run", "discovery"), strict=True):
        for item in items:
            print(f"  {what} {item.id}  {item.label}")
    print(f"  stored files under {', '.join(r.prefixes)}")


def _confirmed(args: argparse.Namespace, word: str) -> bool:
    """`--yes`, or the operator typed `word` at a terminal (as restore.sh asks)."""
    if args.yes:
        return True
    if not sys.stdin.isatty():
        raise ConfigError("this needs a terminal to confirm; add --yes to delete without asking")
    try:
        answer = input(f"This cannot be undone. Type '{word}' to go on: ")
    except EOFError:
        return False
    return answer.strip() == word


def _delete(
    args: argparse.Namespace,
    plan: Callable[[Database], Awaitable[removal.Removal]],
    go: Callable[[Database, Storage, removal.Removal], Awaitable[removal.Removal]],
    word: Callable[[removal.Removal], str],
    *,
    with_runs: bool = True,
) -> int:
    """Show what goes, refuse what may not, ask, delete what was shown (or nothing, should it
    have changed meanwhile) and log the audit line."""
    cfg = _load(args)
    storage = build_storage(cfg.storage)
    found = _with_db(cfg, plan)
    removal.check(found, with_runs=with_runs)  # refused before asking; checked again under lock
    _show_removal(found)
    if not _confirmed(args, word(found)):
        print("not confirmed; nothing was deleted", file=sys.stderr)
        return EXIT_FAILED
    handler = configure_json_logging()  # the audit line, as JSON on stderr
    try:
        done = _with_db(cfg, lambda db: go(db, storage, found))
    finally:
        remove_json_logging(handler)
    print(f"deleted {removal.summary(done)}")
    return EXIT_OK


def _delete_source(args: argparse.Namespace) -> int:
    source_id = _id(args.source_id, "source")
    return _delete(
        args,
        lambda db: removal.plan_source(db, source_id),
        lambda db, storage, found: removal.delete_source(
            db, storage, source_id, with_runs=args.with_runs, expected=found
        ),
        lambda _: "delete",
        with_runs=args.with_runs,
    )


def _delete_project(args: argparse.Namespace) -> int:
    return _delete(
        args,
        lambda db: removal.plan_project(db, args.project),
        lambda db, storage, found: removal.delete_project(
            db, storage, args.project, expected=found
        ),
        lambda found: found.project,
    )


def _doctor(args: argparse.Namespace) -> int:
    from corelata.doctor import run_doctor
    from corelata.schema import CheckStatus

    report = asyncio.run(run_doctor(args.config, probe=not args.no_probe))
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        for c in report.checks:
            print(f"{c.status.value.upper():<5} {c.name}: {c.message}")
            if c.fix and c.status is not CheckStatus.PASS:
                print(f"      fix: {c.fix}")
    return EXIT_OK if report.ok else EXIT_FAILED


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "migrate": _migrate,
    "worker": _worker,
    "ingest": _ingest,
    "status": _status,
    "cancel": _cancel,
    "review": _review,
    "export": _export,
    "doctor": _doctor,
    "sources": _sources,
    "delete-source": _delete_source,
    "delete-project": _delete_project,
    "queue-run": _queue_run,  # `corelata run --project`, dispatched by cli.py
    "queue-discover": _queue_discover,  # `corelata discover --project`
}


def run_command(args: argparse.Namespace, command: str | None = None) -> int:
    try:
        return COMMANDS[command or args.command](args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except DatabaseUnavailable as e:  # before USER_ERRORS: it is a ConfigError
        print(f"error: {e}", file=sys.stderr)
    except USER_ERRORS as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except DocxExportError as e:
        print(f"error: the DOCX export failed: {e}", file=sys.stderr)
    except DB_ERRORS as e:
        print(f"error: cannot reach the database: {error_reason(e)}", file=sys.stderr)
    except QueueUnavailableError as e:
        print(f"error: cannot reach the database: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - last resort: never show a traceback to the user
        print(f"error: internal error: {type(e).__name__}: {e}", file=sys.stderr)
    return EXIT_FAILED

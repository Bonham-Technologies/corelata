"""`corelata-api`: check the installation, then serve. Migrations are not run here (the compose
`migrate` service runs `corelata migrate`); an unmigrated database is refused with the fix."""

import argparse
import sys
from pathlib import Path

import uvicorn
from corelata.config import ConfigError, default_config_path, load_config
from corelata.logs import configure_json_logging, remove_json_logging
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.storage import ProbeLeftover, StorageError, build_storage
from corelata.store.db import database_url
from corelata.store.migrate import ensure_migrated

from corelata_api.app import create_app
from corelata_api.web import missing_index


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corelata-api", description="Corelata REST API")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--web-dir", type=Path, help="serve the built web app from this directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cfg, warnings = load_config(args.config)
        for warning in warnings:
            print(f"{warning.level}: {warning.message}", file=sys.stderr)
        if args.web_dir is not None:
            cfg = cfg.model_copy(
                update={"api": cfg.api.model_copy(update={"web_dir": args.web_dir.resolve()})}
            )
        validate_prompts(cfg, PromptLibrary(cfg.prompts_dir))
        ensure_migrated(database_url(cfg))
        try:
            build_storage(cfg.storage).check_writable()
        except ProbeLeftover as e:  # writable; a stray empty file is no reason to stop
            print(f"warning: {e}", file=sys.stderr)
        if cfg.api.web_dir is not None and (problem := missing_index(cfg.api.web_dir)):
            raise ConfigError(problem)
    except (ConfigError, StorageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    handler = configure_json_logging()
    try:
        uvicorn.run(
            create_app(cfg, args.config.resolve()),
            host=args.host,
            port=args.port,
            timeout_graceful_shutdown=5,
        )
    finally:
        remove_json_logging(handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

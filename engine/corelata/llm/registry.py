"""Construct backends from config; third parties add kinds via the corelata.backends group."""

import os
from collections.abc import Callable
from importlib.metadata import entry_points

from corelata.config import BackendConfig, ConfigError, CorelataConfig
from corelata.llm.openai_compat import OpenAICompatBackend
from corelata.llm.types import Backend

BackendFactory = Callable[[str, BackendConfig], Backend]


def _openai_compat(name: str, cfg: BackendConfig) -> Backend:
    api_key = os.environ.get(cfg.api_key_env) if cfg.api_key_env else None
    return OpenAICompatBackend(
        name,
        cfg.base_url,
        api_key=api_key,
        max_concurrency=cfg.max_concurrency,
        timeout_s=cfg.timeout_s,
    )


def available_kinds() -> dict[str, BackendFactory]:
    kinds: dict[str, BackendFactory] = {"openai_compat": _openai_compat}
    for ep in entry_points(group="corelata.backends"):
        kinds.setdefault(ep.name, ep.load())
    return kinds


def build_backends(cfg: CorelataConfig) -> dict[str, Backend]:
    kinds = available_kinds()
    backends: dict[str, Backend] = {}
    for name, bcfg in cfg.backends.items():
        factory = kinds.get(bcfg.kind)
        if factory is None:
            raise ConfigError(
                f"backend '{name}': unknown kind '{bcfg.kind}' "
                f"(available: {', '.join(sorted(kinds))})"
            )
        backends[name] = factory(name, bcfg)
    return backends

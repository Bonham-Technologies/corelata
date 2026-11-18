"""Versioned prompt templates. Built-ins live in templates/<id>/v<N>.j2; deployments may
override any prompt by placing templates/<id>/v<N>.j2 files in config.prompts_dir."""

import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, StrictUndefined

BUILTIN_DIR = Path(__file__).parent / "templates"
_VERSION_RE = re.compile(r"^v(\d+)\.j2$")
_ID_RE = re.compile(r"^[a-z0-9_\-]+$")


class PromptNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class RenderedPrompt:
    id: str
    version: int
    text: str


class PromptLibrary:
    def __init__(self, override_dir: Path | None = None) -> None:
        self._dirs = [d for d in (override_dir, BUILTIN_DIR) if d is not None]
        self._env = Environment(undefined=StrictUndefined, autoescape=False)

    def resolve(self, prompt_id: str) -> tuple[int, Path]:
        if not _ID_RE.match(prompt_id):
            raise PromptNotFoundError(f"invalid prompt id '{prompt_id}'")
        for base in self._dirs:
            pdir = base / prompt_id
            if not pdir.is_dir():
                continue
            versions = sorted(
                int(m.group(1)) for f in pdir.iterdir() if (m := _VERSION_RE.match(f.name))
            )
            if versions:
                return versions[-1], pdir / f"v{versions[-1]}.j2"
        raise PromptNotFoundError(
            f"no template for prompt '{prompt_id}' in {', '.join(str(d) for d in self._dirs)}"
        )

    def render(self, prompt_id: str, **variables: object) -> RenderedPrompt:
        version, path = self.resolve(prompt_id)
        template = self._env.from_string(path.read_text(encoding="utf-8"))
        return RenderedPrompt(prompt_id, version, template.render(**variables).strip())

    def versions(self, prompt_ids: list[str]) -> dict[str, int]:
        return {pid: self.resolve(pid)[0] for pid in prompt_ids}

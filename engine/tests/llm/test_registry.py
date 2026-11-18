import pytest

from corelata.config import ConfigError
from corelata.llm import registry
from corelata.llm.openai_compat import OpenAICompatBackend


class _EP:
    def __init__(self, name, obj):
        self.name = name
        self._obj = obj

    def load(self):
        return self._obj


async def test_builds_openai_compat_backends(make_config, monkeypatch):
    monkeypatch.setenv("K", "secret")
    cfg = make_config(backends={"fake": {"base_url": "http://x/v1", "api_key_env": "K"}})
    backends = registry.build_backends(cfg)
    assert isinstance(backends["fake"], OpenAICompatBackend)
    assert backends["fake"].name == "fake"
    await backends["fake"].aclose()


def test_unknown_kind_is_config_error(make_config):
    cfg = make_config(backends={"fake": {"kind": "grpc", "base_url": "http://x"}})
    with pytest.raises(ConfigError, match="unknown kind 'grpc'.*openai_compat"):
        registry.build_backends(cfg)


def test_plugin_backends_are_loaded(make_config, monkeypatch):
    made = {}

    def factory(name, bcfg):
        made[name] = bcfg.base_url
        return object()

    monkeypatch.setattr(registry, "entry_points", lambda group: [_EP("grpc", factory)])
    cfg = make_config(backends={"fake": {"kind": "grpc", "base_url": "grpc://x"}})
    backends = registry.build_backends(cfg)
    assert made == {"fake": "grpc://x"}
    assert set(backends) == {"fake"}

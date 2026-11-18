import pytest

from corelata.ingest.units import UnitIndex
from corelata.stages.context import StageContext
from corelata.standards.loader import load_pack
from corelata.testing.sources import text_source

PORT = [
    "The port of Varna expanded its container capacity in 2025.",
    "Capacity expansion was financed by a state bank.",
    "Container traffic through Varna rose 40 percent.",
]


@pytest.fixture
def pack():
    return load_pack("icd203-base")


@pytest.fixture
def make_ctx(make_config, make_runner, pack):
    def _make(
        *sources, statement="Varna port capacity expansion matters to shippers", cfg=None, **kw
    ) -> StageContext:
        cfg = cfg or make_config()
        sources = list(sources) or [text_source("src1", *PORT)]
        return StageContext(
            cfg=cfg,
            runner=make_runner(cfg),
            pack=pack,
            sources=sources,
            index=UnitIndex.from_sources(sources),
            value_statement=statement,
            **kw,
        )

    return _make

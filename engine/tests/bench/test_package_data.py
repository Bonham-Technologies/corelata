import tomllib
from pathlib import Path

from corelata.bench import REAL_SCENARIOS_DIR, SCENARIO_SETS, SCENARIOS_DIR, scenarios_path
from corelata.scenarios import load_scenarios

REAL_NAMES = [
    "borrowed-quotation",
    "conflicting-rail-figures",
    "corroborated-port-expansion",
    "mixed-relevance-sources",
    "off-topic-sources",
    "overreaching-statement",
    "quarterly-throughput-figures",
    "quoted-customs-figures",
    "thin-harvest-outlook",
    "unverified-social-post",
]


def test_shipped_scenarios_load_and_are_the_known_set():
    names = [s.name for s in load_scenarios(SCENARIOS_DIR)]
    assert names == [
        "badterm-fixed-one-loop",
        "clean-single-source",
        "clean-two-sources",
        "gate-rejected",
        "long-source-digested",
        "many-sources-writer-budget",
        "max-iterations-zero",
        "quotes-fabricated-fixed-one-loop",
        "quotes-faithful-clean",
        "thin-material",
        "unsourced-fixed-one-loop",
        "unsourced-unfixable",
    ]
    assert all(p.suffix == ".yaml" for p in SCENARIOS_DIR.iterdir() if p.is_file())


def test_the_real_set_ships_in_the_wheel_beside_the_synthetic_set():
    names = [s.name for s in load_scenarios(REAL_SCENARIOS_DIR)]
    assert names == REAL_NAMES
    assert set(names).isdisjoint(s.name for s in load_scenarios(SCENARIOS_DIR))
    assert all(p.suffix == ".yaml" for p in REAL_SCENARIOS_DIR.iterdir() if p.is_file())
    assert SCENARIO_SETS == {"synthetic": SCENARIOS_DIR, "real": REAL_SCENARIOS_DIR}
    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    artifacts = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]
    assert "corelata/bench/scenarios-real/*.yaml" in artifacts


def test_scenarios_path_resolves_set_names_before_paths():
    assert scenarios_path("synthetic") == SCENARIOS_DIR
    assert scenarios_path("real") == REAL_SCENARIOS_DIR
    assert scenarios_path("./real") == Path("./real")  # a directory that is called real
    assert scenarios_path("/srv/scenarios") == Path("/srv/scenarios")

import tomllib
from pathlib import Path

import corelata
from corelata.version import BUILD_VERSION_ENV, build_version, version_line


def test_version_matches_pyproject():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert corelata.__version__ == pyproject["project"]["version"]


def test_build_version_falls_back_to_the_package_version():
    assert BUILD_VERSION_ENV == "CORELATA_BUILD_VERSION"
    assert build_version({}) == corelata.__version__
    assert build_version({BUILD_VERSION_ENV: "   "}) == corelata.__version__
    assert version_line({}) == f"corelata {corelata.__version__}"


def test_build_version_comes_from_the_image_environment(monkeypatch):
    monkeypatch.setenv(BUILD_VERSION_ENV, " 1.2.0-g1234abc ")
    assert build_version() == "1.2.0-g1234abc"
    assert version_line() == f"corelata {corelata.__version__} (build 1.2.0-g1234abc)"
    same = {BUILD_VERSION_ENV: corelata.__version__}
    assert version_line(same) == f"corelata {corelata.__version__}"

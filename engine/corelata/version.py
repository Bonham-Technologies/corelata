"""Which version Corelata reports (spec §12). `__version__` is the Python package's; the bundle
that ships it may carry another (the git tag, or `<package>-g<sha>` between releases), baked into
the image as CORELATA_BUILD_VERSION by deploy/docker/app.Dockerfile. Health, system/info, the web
footer and `corelata --version` report the build version when there is one, so what an operator
sees agrees with VERSION, the image label and manifest.json."""

import os
from collections.abc import Mapping

from corelata import __version__

BUILD_VERSION_ENV = "CORELATA_BUILD_VERSION"


def build_version(environ: Mapping[str, str] | None = None) -> str:
    """The bundle version when the image carries one, else the package version."""
    env = os.environ if environ is None else environ
    return env.get(BUILD_VERSION_ENV, "").strip() or __version__


def version_line(environ: Mapping[str, str] | None = None) -> str:
    """`corelata 0.1.0`, or `corelata 0.1.0 (build 1.2.0)` when the build differs."""
    build = build_version(environ)
    if build == __version__:
        return f"corelata {__version__}"
    return f"corelata {__version__} (build {build})"

"""CI check: the Modal app imports (no Modal account needed) and has the functions the hosted
config and README rely on, with the endpoint labels app.py defines as constants. It also imports
app.py the way a Modal container does (as /root/app.py, with modal.is_local() False), which has
no repository around it. Run: python check_app.py

The functions are found by scanning app.py's module globals for modal.Function objects (the
deprecated App.registered_functions goes away in modal 1.7.0)."""

import sys
import types
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import modal  # noqa: E402

import app  # noqa: E402

FUNCTIONS = ["api", "cron", "doctor", "kick", "migrate", "purge", "seed", "worker"]
EXPECTED_LABELS = {"APP_NAME": "corelata", "API_LABEL": "corelata-api", "KICK_LABEL": "corelata-kick"}


functions = sorted(n for n, o in vars(app).items() if isinstance(o, modal.Function))

problems = []
if functions != FUNCTIONS:
    problems.append(f"functions {functions}, expected {FUNCTIONS}")
labels = {"APP_NAME": app.APP_NAME, "API_LABEL": app.API_LABEL, "KICK_LABEL": app.KICK_LABEL}
if labels != EXPECTED_LABELS:
    problems.append(f"labels {labels}, expected {EXPECTED_LABELS}")


def import_as_in_a_container() -> types.ModuleType:
    """Run settings.py and app.py from /root, as Modal mounts them, with modal.is_local()
    False; returns the app module."""
    modules = {}
    with mock.patch.object(modal, "is_local", lambda: False), mock.patch.dict(sys.modules):
        for name in ("settings", "app"):
            module = types.ModuleType(name)
            module.__file__ = f"/root/{name}.py"
            sys.modules[name] = module
            source = (HERE / f"{name}.py").read_text(encoding="utf-8")
            exec(compile(source, module.__file__, "exec"), module.__dict__)
            modules[name] = module
    return modules["app"]


try:
    remote = import_as_in_a_container()
    if remote.REPO != Path("/"):
        problems.append(f"in a container REPO is {remote.REPO}, expected /")
except Exception as e:  # report every problem at once, not only the first
    problems.append(f"app.py fails to import in a container: {type(e).__name__}: {e}")
if problems:
    sys.exit("check_app: " + "; ".join(problems))
print(functions)

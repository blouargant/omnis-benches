"""
Check auto-discovery.

Every non-underscore module in this package is imported here, which runs its
`@check(...)` decorators and registers the checks. To ADD a test, just drop a
new `checks/<name>.py` file with `@check` functions — no wiring needed.

(Modules whose name starts with "_" are skipped: they are shared helpers, not
check modules.)
"""

import importlib
import os
import pkgutil

_pkg_dir = os.path.dirname(__file__)

for _finder, _name, _ispkg in pkgutil.iter_modules([_pkg_dir]):
    if _name.startswith("_"):
        continue
    importlib.import_module(__name__ + "." + _name)

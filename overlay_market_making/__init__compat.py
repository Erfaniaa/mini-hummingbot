"""
Compatibility package to allow importing modules from the internal project
directory named 'mini-hummingbot'. Python packages cannot contain a dash,
so we point this package's module search path (__path__) to that directory.
"""
from __future__ import annotations

import pathlib

# Point this package to the actual source directory
_this_dir = pathlib.Path(__file__).resolve().parent
_real_src = _this_dir.parent / "mini-hummingbot"

# Set __path__ so that 'mini_hummingbot.core', '...connectors', etc. are
# resolved inside the 'mini-hummingbot' directory.
__path__ = [str(_real_src)]



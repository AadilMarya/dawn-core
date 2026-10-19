"""Expose the bundled Remote Script as the ``control_surface`` namespace package.

The Remote Script is installed in Live as ``DAWN`` but imports its own modules
through the ``control_surface.DAWN`` name, so tests reach it the same way.
"""

from __future__ import annotations

import sys
import types

import dawn_osc

if "control_surface" not in sys.modules:
    _namespace = types.ModuleType("control_surface")
    _namespace.__path__ = [str(dawn_osc.remote_script_root())]
    sys.modules["control_surface"] = _namespace

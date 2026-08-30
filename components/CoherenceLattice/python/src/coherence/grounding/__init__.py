"""Canonical grounding package with the bounded legacy-module compatibility path."""
from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
_COMPATIBILITY_ROOT = Path(__file__).resolve().parents[4] / "coherence" / "grounding"
if _COMPATIBILITY_ROOT.is_dir() and str(_COMPATIBILITY_ROOT) not in __path__:
    __path__.append(str(_COMPATIBILITY_ROOT))

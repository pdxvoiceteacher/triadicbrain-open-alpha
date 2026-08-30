"""Coherence bridge and utilities."""

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
_ROOT_COHERENCE = Path(__file__).resolve().parents[3] / "coherence"
if _ROOT_COHERENCE.is_dir():
    _root_coherence = str(_ROOT_COHERENCE)
    if _root_coherence not in __path__:
        __path__.append(_root_coherence)

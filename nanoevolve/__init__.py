from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("nanoevolve")
except PackageNotFoundError:
    __version__ = "0+unknown"

from .engine import evolve
from .mutation import OpenAICompatibleModel
from .types import Evaluation, EvolutionEvent, Record

__all__ = [
    "Evaluation",
    "EvolutionEvent",
    "OpenAICompatibleModel",
    "Record",
    "__version__",
    "evolve",
]

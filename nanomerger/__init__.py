"""NanoMerger: embeddable CAD merging core. Importing this package does not load Qt."""

__version__ = "0.1.1"

from .errors import (
    CancelledError,
    ConversionError,
    DependencyError,
    InputError,
    NanoMergerError,
    OutputExistsError,
    UnsupportedDrawingError,
)
from .models import MergeOptions, MergeResult, Progress, SheetInfo, SourceFile


def merge_folder(*args, **kwargs):
    """Lazy wrapper around :func:`nanomerger.merger.merge_folder`."""
    from .merger import merge_folder as _merge_folder

    return _merge_folder(*args, **kwargs)


def scan_folder(*args, **kwargs):
    from .discovery import scan_folder as _scan_folder

    return _scan_folder(*args, **kwargs)


__all__ = [
    "__version__",
    "merge_folder",
    "scan_folder",
    "MergeOptions",
    "MergeResult",
    "Progress",
    "SheetInfo",
    "SourceFile",
    "NanoMergerError",
    "InputError",
    "ConversionError",
    "DependencyError",
    "CancelledError",
    "OutputExistsError",
    "UnsupportedDrawingError",
]

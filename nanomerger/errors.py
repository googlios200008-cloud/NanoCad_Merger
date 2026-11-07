"""Stable exception types for the CLI and host applications such as Engi."""

from __future__ import annotations


class NanoMergerError(Exception):
    """Expected, user-actionable failure. ``code`` is also the CLI exit status."""

    code = 1

    def __init__(self, message: str, *, details: str = "") -> None:
        super().__init__(message)
        self.details = details


class InputError(NanoMergerError):
    code = 2


class ConversionError(NanoMergerError):
    code = 3


class CancelledError(NanoMergerError):
    code = 4


class OutputExistsError(NanoMergerError):
    code = 5


class UnsupportedDrawingError(InputError):
    """The drawing contains objects that cannot be merged without possible loss."""


class DependencyError(ConversionError):
    """An optional external executable or Python package is unavailable."""

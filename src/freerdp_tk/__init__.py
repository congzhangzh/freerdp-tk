"""freerdp-tk: a small cross-platform Tkinter launcher for the FreeRDP clients."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("freerdp-tk")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0"

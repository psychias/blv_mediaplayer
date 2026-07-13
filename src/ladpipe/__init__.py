"""ladpipe — offline lecture audio-description pipeline core (UI-agnostic).

Importing this package pulls in zero heavy/GPU/network dependencies; the real
model backends lazy-import their heavy libs only when selected by config.
"""

from __future__ import annotations

__version__ = "0.1.0"

"""Sun2 test common functions, etc."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, tzinfo
from unittest.mock import MagicMock

DtNowMock = tuple[Callable[[tzinfo | None], datetime], MagicMock]

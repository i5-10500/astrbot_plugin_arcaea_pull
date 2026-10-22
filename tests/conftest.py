"""Provide only the AstrBot logger boundary for runtime-independent unit tests."""

import sys
import types
from unittest.mock import Mock

astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
api.logger = Mock(spec=["info", "warning", "error", "exception"])
astrbot.api = api
sys.modules["astrbot"] = astrbot
sys.modules["astrbot.api"] = api

import os
import subprocess
import sys
import textwrap
import zipfile

from scripts.build_release import ARCHIVE, build


def test_release_imports_through_astrbot_package_path(tmp_path):
    """Catch imports that only work when the plugin directory is on sys.path."""
    build()
    plugin_dir = tmp_path / "data" / "plugins" / "astrbot_plugin_arcaea_pull"
    plugin_dir.mkdir(parents=True)
    with zipfile.ZipFile(ARCHIVE) as archive:
        archive.extractall(plugin_dir)

    smoke_test = textwrap.dedent(
        """
        import importlib
        import sys
        import types
        from pathlib import Path

        class AstrBotConfig(dict):
            pass

        class MessageChain:
            def message(self, _value):
                return self

        class Star:
            def __init__(self, context):
                self.context = context

        class StarTools:
            @staticmethod
            def get_data_dir(_name):
                return Path.cwd() / "plugin-data"

        def identity_decorator(*_args, **_kwargs):
            def decorate(value):
                return value
            return decorate

        def command_group(*_args, **_kwargs):
            def decorate(value):
                value.command = identity_decorator
                return value
            return decorate

        astrbot = types.ModuleType("astrbot")
        api = types.ModuleType("astrbot.api")
        event = types.ModuleType("astrbot.api.event")
        star = types.ModuleType("astrbot.api.star")

        api.AstrBotConfig = AstrBotConfig
        api.logger = types.SimpleNamespace(error=lambda *_args: None,
                                           exception=lambda *_args: None)
        event.AstrMessageEvent = object
        event.MessageChain = MessageChain
        event.filter = types.SimpleNamespace(
            PermissionType=types.SimpleNamespace(ADMIN="admin"),
            command_group=command_group,
            permission_type=identity_decorator,
        )
        star.Context = object
        star.Star = Star
        star.StarTools = StarTools
        star.register = identity_decorator

        sys.modules.update({
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
        })

        module = importlib.import_module(
            "data.plugins.astrbot_plugin_arcaea_pull.main"
        )
        assert module.__version__ == "0.3.0"
        assert module.ArcaeaPullPlugin.__module__ == module.__name__
        plugin = module.ArcaeaPullPlugin(object(), AstrBotConfig())
        assert plugin.downloader._client_timeout().total is None
        assert plugin.downloader.read_timeout == 120
        assert module._schedule_summary(AstrBotConfig()) == (
            "every 30m from local 00:00; extras=none"
        )
        assert module._schedule_summary(
            AstrBotConfig(check_interval_minutes=0)
        ) == "INVALID"
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", smoke_test],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

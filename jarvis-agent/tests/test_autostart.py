from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import patch

from jarvis.desktop.autostart import (
    DEFAULT_LABEL,
    build_launch_agent_plist,
    get_autostart_status,
    install_launch_agent,
    restart_launch_agent,
    uninstall_launch_agent,
)


def test_build_launch_agent_plist_shape(tmp_path: Path):
    project_root = tmp_path / "repo"
    logs_dir = tmp_path / "logs"
    project_root.mkdir()
    payload = build_launch_agent_plist(
        label=DEFAULT_LABEL,
        project_root=project_root,
        python_executable="/opt/venv/bin/python",
        logs_dir=logs_dir,
    )

    assert payload["Label"] == DEFAULT_LABEL
    assert payload["ProgramArguments"] == ["/opt/venv/bin/python", "-m", "jarvis", "--desktop"]
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["EnvironmentVariables"]["PYTHONPATH"] == str(project_root / "src")


def test_install_writes_plist_and_bootstraps(tmp_path: Path):
    plist_path = tmp_path / "LaunchAgents" / "com.jarvis.agent.desktop.plist"

    calls = []

    class _Res:
        def __init__(self, returncode=0, stderr=""):
            self.returncode = returncode
            self.stderr = stderr

    def _fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        return _Res(returncode=0)

    with patch("jarvis.desktop.autostart.sys.platform", "darwin"), \
         patch("jarvis.desktop.autostart._run", side_effect=_fake_run):
        ok, msg, written = install_launch_agent(
            project_root=tmp_path,
            logs_dir=tmp_path / "logs",
            plist_path=plist_path,
            python_executable="/usr/bin/python3",
        )

    assert ok is True
    assert "instalado" in msg.lower()
    assert written == plist_path
    assert plist_path.exists()
    data = plistlib.loads(plist_path.read_bytes())
    assert data["ProgramArguments"] == ["/usr/bin/python3", "-m", "jarvis", "--desktop"]
    assert any(cmd[:2] == ["launchctl", "bootstrap"] for cmd in calls)


def test_uninstall_removes_plist(tmp_path: Path):
    plist_path = tmp_path / "LaunchAgents" / "com.jarvis.agent.desktop.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text("x", encoding="utf-8")

    with patch("jarvis.desktop.autostart.sys.platform", "darwin"), \
         patch("jarvis.desktop.autostart._run"):
        ok, msg, removed = uninstall_launch_agent(plist_path=plist_path)

    assert ok is True
    assert "eliminado" in msg.lower()
    assert removed == plist_path
    assert not plist_path.exists()


def test_status_reads_launchctl_result(tmp_path: Path):
    plist_path = tmp_path / "LaunchAgents" / "com.jarvis.agent.desktop.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text("x", encoding="utf-8")

    class _Res:
        def __init__(self, returncode=0, stderr=""):
            self.returncode = returncode
            self.stderr = stderr

    with patch("jarvis.desktop.autostart.sys.platform", "darwin"), \
         patch("jarvis.desktop.autostart._run", return_value=_Res(returncode=0)):
        st = get_autostart_status(plist_path=plist_path)

    assert st.installed is True
    assert st.loaded is True


def test_restart_calls_uninstall_then_install(tmp_path: Path):
    plist_path = tmp_path / "LaunchAgents" / "com.jarvis.agent.desktop.plist"

    with patch("jarvis.desktop.autostart.uninstall_launch_agent", return_value=(True, "ok", plist_path)) as m_un, \
         patch("jarvis.desktop.autostart.install_launch_agent", return_value=(True, "ok", plist_path)) as m_in:
        ok, msg, plist = restart_launch_agent(
            project_root=tmp_path,
            logs_dir=tmp_path / "logs",
            plist_path=plist_path,
        )

    assert ok is True
    assert "reiniciado" in msg.lower()
    assert plist == plist_path
    m_un.assert_called_once()
    m_in.assert_called_once()

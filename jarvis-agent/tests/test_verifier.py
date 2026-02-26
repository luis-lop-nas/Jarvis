from __future__ import annotations

from pathlib import Path

from jarvis.agent.verifier import VerifyContext, verify


def test_verify_filesystem_move_ok(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("hello", encoding="utf-8")
    src.rename(dst)
    report = verify(
        "filesystem",
        {"action": "move", "path": str(src), "destination": str(dst)},
        {"action": "move", "source": str(src), "destination": str(dst)},
        VerifyContext(),
    )
    assert report.status == "ok"


def test_verify_filesystem_delete_ok(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("x", encoding="utf-8")
    p.unlink()
    report = verify(
        "filesystem",
        {"action": "delete", "path": str(p)},
        {"action": "delete", "path": str(p), "deleted": True},
        VerifyContext(),
    )
    assert report.status == "ok"


def test_verify_shell_exit_nonzero_fail() -> None:
    report = verify(
        "shell",
        {"command": "false"},
        {"returncode": 1, "stderr": "boom"},
        VerifyContext(),
    )
    assert report.status == "fail"


def test_verify_open_app_ok_when_process_exists(monkeypatch) -> None:
    from jarvis.agent import verifier as v

    monkeypatch.setattr(v, "_is_app_running", lambda _: True)
    report = verify(
        "open_app",
        {"app": "Safari"},
        {"returncode": 0, "opened_app": "Safari"},
        VerifyContext(),
    )
    assert report.status == "ok"


def test_verify_download_ok_if_file_exists(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    report = verify(
        "download_file",
        {"url": "https://example.com/f.bin"},
        {"success": True, "path": str(p), "size_bytes": 3},
        VerifyContext(),
    )
    assert report.status == "ok"

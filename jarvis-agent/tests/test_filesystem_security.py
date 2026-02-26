"""
tests/test_filesystem_security.py

Tests de seguridad para la tool filesystem:
- Path traversal
- Acceso a directorios prohibidos del sistema
- Acceso a directorios sensibles del usuario (~/.ssh, ~/.aws, etc.)
- Límites de tamaño en lectura y escritura
- Inputs maliciosos (null bytes, rutas relativas escapadas)
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.tools.filesystem import (
    MAX_READ_BYTES,
    MAX_WRITE_BYTES,
    _is_safe_path,
    run_filesystem,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write(tmp_path: Path, filename: str, content: str) -> Path:
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# _is_safe_path
# ─────────────────────────────────────────────────────────────────────────────

class TestIsSafePath:
    def test_allows_home_documents(self, tmp_path):
        assert _is_safe_path(tmp_path) is True

    def test_blocks_system_dir(self):
        assert _is_safe_path(Path("/System")) is False

    def test_blocks_usr(self):
        assert _is_safe_path(Path("/usr/local/bin/python")) is False

    def test_blocks_bin(self):
        assert _is_safe_path(Path("/bin/bash")) is False

    def test_blocks_etc(self):
        assert _is_safe_path(Path("/etc/passwd")) is False

    def test_blocks_ssh_dir(self):
        ssh = Path.home() / ".ssh"
        assert _is_safe_path(ssh) is False

    def test_blocks_ssh_key(self):
        key = Path.home() / ".ssh" / "id_rsa"
        assert _is_safe_path(key) is False

    def test_blocks_aws_credentials(self):
        creds = Path.home() / ".aws" / "credentials"
        assert _is_safe_path(creds) is False

    def test_blocks_gnupg(self):
        gpg = Path.home() / ".gnupg"
        assert _is_safe_path(gpg) is False


# ─────────────────────────────────────────────────────────────────────────────
# read_text — límite de tamaño
# ─────────────────────────────────────────────────────────────────────────────

class TestReadTextSecurity:
    def test_reads_normal_file(self, tmp_path):
        p = _write(tmp_path, "hello.txt", "hola mundo")
        result = run_filesystem({"action": "read_text", "path": str(p)})
        assert result["content"] == "hola mundo"

    def test_blocks_oversized_file(self, tmp_path):
        p = tmp_path / "big.bin"
        p.write_bytes(b"x")
        # Mockear solo el stat de la Path resuelta para simular un archivo grande
        import unittest.mock as _um
        orig_stat = p.stat()

        class _FakeStat:
            st_size = MAX_READ_BYTES + 1

        with _um.patch("pathlib.Path.stat", return_value=_FakeStat()):
            with pytest.raises(ValueError, match="demasiado grande"):
                run_filesystem({"action": "read_text", "path": str(p)})

    def test_blocks_ssh_key(self):
        """Intentar leer ~/.ssh/id_rsa debe fallar con PermissionError."""
        fake_ssh = str(Path.home() / ".ssh" / "id_rsa")
        with pytest.raises(PermissionError):
            run_filesystem({"action": "read_text", "path": fake_ssh})

    def test_blocks_aws_credentials(self):
        fake_aws = str(Path.home() / ".aws" / "credentials")
        with pytest.raises(PermissionError):
            run_filesystem({"action": "read_text", "path": fake_aws})

    def test_blocks_etc_passwd(self):
        with pytest.raises(PermissionError):
            run_filesystem({"action": "read_text", "path": "/etc/passwd"})


# ─────────────────────────────────────────────────────────────────────────────
# write_text — límite de tamaño
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteTextSecurity:
    def test_writes_normal_content(self, tmp_path):
        p = tmp_path / "out.txt"
        result = run_filesystem({"action": "write_text", "path": str(p), "content": "hello"})
        assert result["bytes"] == 5
        assert p.read_text() == "hello"

    def test_blocks_oversized_content(self, tmp_path):
        p = tmp_path / "big.txt"
        big = "x" * (MAX_WRITE_BYTES + 1)
        with pytest.raises(ValueError, match="demasiado grande"):
            run_filesystem({"action": "write_text", "path": str(p), "content": big})

    def test_blocks_write_to_system_dir(self):
        with pytest.raises(PermissionError):
            run_filesystem({
                "action": "write_text",
                "path": "/usr/local/jarvis_test.txt",
                "content": "pwned",
            })

    def test_blocks_write_to_etc(self):
        with pytest.raises(PermissionError):
            run_filesystem({
                "action": "write_text",
                "path": "/etc/jarvis_test.txt",
                "content": "pwned",
            })


# ─────────────────────────────────────────────────────────────────────────────
# Path traversal
# ─────────────────────────────────────────────────────────────────────────────

class TestPathTraversal:
    def test_resolves_and_blocks_traversal_to_etc(self, tmp_path):
        """../../etc/passwd desde un directorio seguro debe bloquearse."""
        traversal = str(tmp_path / ".." / ".." / ".." / "etc" / "passwd")
        with pytest.raises(PermissionError):
            run_filesystem({"action": "read_text", "path": traversal})

    def test_resolves_and_blocks_traversal_to_ssh(self, tmp_path):
        traversal = str(tmp_path / ".." / ".." / ".." / ".ssh" / "id_rsa")
        with pytest.raises(PermissionError):
            run_filesystem({"action": "read_text", "path": traversal})

    def test_safe_relative_path_inside_tmp(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "file.txt"
        f.write_text("ok", encoding="utf-8")
        # Ruta relativa desde tmp_path que sigue dentro del directorio
        result = run_filesystem({
            "action": "read_text",
            "path": "file.txt",
            "root_dir": str(sub),
        })
        assert result["content"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# delete — requiere recursive=True para directorios
# ─────────────────────────────────────────────────────────────────────────────

class TestDeleteSecurity:
    def test_delete_file_ok(self, tmp_path):
        p = _write(tmp_path, "to_delete.txt", "bye")
        result = run_filesystem({"action": "delete", "path": str(p)})
        assert result["deleted"] is True
        assert not p.exists()

    def test_delete_dir_requires_recursive(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        with pytest.raises(PermissionError, match="recursive"):
            run_filesystem({"action": "delete", "path": str(d)})

    def test_delete_dir_with_recursive(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        (d / "file.txt").write_text("x")
        result = run_filesystem({"action": "delete", "path": str(d), "recursive": True})
        assert result["deleted"] is True
        assert not d.exists()

    def test_delete_system_dir_blocked(self):
        with pytest.raises(PermissionError):
            run_filesystem({"action": "delete", "path": "/usr", "recursive": True})


# ─────────────────────────────────────────────────────────────────────────────
# Inputs maliciosos varios
# ─────────────────────────────────────────────────────────────────────────────

class TestMaliciousInputs:
    def test_empty_action_raises(self):
        with pytest.raises(ValueError, match="action"):
            run_filesystem({"action": ""})

    def test_missing_path_raises_for_read(self):
        with pytest.raises(ValueError):
            run_filesystem({"action": "read_text"})

    def test_null_in_path_handled(self, tmp_path):
        """Null bytes en path deben causar error controlado, no crash."""
        with pytest.raises((ValueError, PermissionError, OSError)):
            run_filesystem({"action": "read_text", "path": str(tmp_path) + "\x00evil"})

    def test_very_long_path(self, tmp_path):
        """Rutas muy largas no deben causar crash no controlado."""
        long_name = "a" * 300
        p = tmp_path / long_name
        with pytest.raises((OSError, ValueError, FileNotFoundError)):
            run_filesystem({"action": "read_text", "path": str(p)})

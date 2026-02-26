from __future__ import annotations

from jarvis.desktop.doctor import doctor_result_to_dict, run_desktop_doctor


def test_doctor_reports_ok_when_all_good(monkeypatch):
    class _St:
        installed = True
        loaded = True

    monkeypatch.setattr("jarvis.desktop.doctor.get_autostart_status", lambda: _St())
    monkeypatch.setattr("jarvis.desktop.doctor._check_microphone_permission", lambda: "granted")
    monkeypatch.setattr("jarvis.desktop.doctor._check_accessibility_permission", lambda: "granted")

    report = doctor_result_to_dict(run_desktop_doctor())
    assert report["ok"] is True
    assert report["issues"] == []


def test_doctor_reports_issues(monkeypatch):
    class _St:
        installed = False
        loaded = False

    monkeypatch.setattr("jarvis.desktop.doctor.get_autostart_status", lambda: _St())
    monkeypatch.setattr("jarvis.desktop.doctor._check_microphone_permission", lambda: "denied")
    monkeypatch.setattr("jarvis.desktop.doctor._check_accessibility_permission", lambda: "denied")

    report = doctor_result_to_dict(run_desktop_doctor())
    assert report["ok"] is False
    assert any("Autoarranque no instalado" in i for i in report["issues"])
    assert any("micrófono" in i.lower() for i in report["issues"])
    assert any("accesibilidad" in i.lower() for i in report["issues"])

import os

from openmacros.daemon import dbus_service as ds
from openmacros.daemon.config import Config
from openmacros.daemon.manager import Manager


def make(monkeypatch, uid, pid=123, sandboxed=False, fail=False):
    svc = ds.DBusService(Manager(Config(None)))

    def creds(sender):
        if fail:
            raise RuntimeError("sem credenciais")
        return uid, pid
    monkeypatch.setattr(svc, "_credentials", creds)
    monkeypatch.setattr(ds, "is_sandboxed", lambda p: sandboxed)
    return svc


def test_same_uid_allowed(monkeypatch):
    svc = make(monkeypatch, os.getuid())
    assert svc.authorize(":1.5", "SetAssignment") is None
    assert svc.authorize(":1.5", "GetDevices") is None


def test_other_uid_denied(monkeypatch):
    svc = make(monkeypatch, os.getuid() + 1)
    assert svc.authorize(":1.5", "GetDevices")


def test_sandbox_read_only(monkeypatch):
    svc = make(monkeypatch, os.getuid(), sandboxed=True)
    assert svc.authorize(":1.5", "GetDevices") is None
    for method in ("SetAssignment", "SetSetting", "ChangeHost", "ResetDevice"):
        assert svc.authorize(":1.5", method)


def test_fail_closed_and_cache(monkeypatch):
    assert make(monkeypatch, 0, fail=True).authorize(":1.9", "GetDevices")
    svc = make(monkeypatch, os.getuid())
    svc.authorize(":1.5", "GetDevices")
    monkeypatch.setattr(svc, "_credentials", lambda s: (_ for _ in ()).throw(RuntimeError()))
    assert svc.authorize(":1.5", "GetDevices") is None  # veio do cache


def test_new_write_methods_are_authorized_as_writes(monkeypatch):
    svc = make(monkeypatch, os.getuid(), sandboxed=True)
    for method in ("SetProfileAssignment", "SetProfileSetting", "RemoveProfile", "SaveSmartAction",
                   "DeleteSmartAction", "RunAction", "DebugSetActiveApp"):
        assert svc.authorize(":1.5", method), method
    for method in ("GetActiveApp", "GetRecentApps", "GetSmartActions"):
        assert svc.authorize(":1.5", method) is None
    other = make(monkeypatch, os.getuid() + 1)
    for method in ("RunAction", "SaveSmartAction", "GetActiveApp"):
        assert other.authorize(":1.5", method)


def test_debug_method_only_in_fake_introspection():
    assert "DebugSetActiveApp" not in ds.introspection_xml(False)
    assert "DebugSetActiveApp" in ds.introspection_xml(True)
    assert "RunAction" in ds.introspection_xml(False)

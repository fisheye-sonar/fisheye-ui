import shutil
import sys

import torch

from fisheye_ui.routes import platform as platform_module


class TestDeviceAvailability:
    def test_cpu_only(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
        recommended, devices = platform_module._device_availability()
        assert recommended == "cpu"
        assert devices == ["cpu"]

    def test_cuda_available_is_recommended(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
        recommended, devices = platform_module._device_availability()
        assert recommended == "cuda"
        assert devices == ["cpu", "cuda"]

    def test_mps_available_is_recommended_over_cpu(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
        recommended, devices = platform_module._device_availability()
        assert recommended == "mps"
        assert devices == ["cpu", "mps"]

    def test_cuda_preferred_over_mps_when_both_available(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
        recommended, devices = platform_module._device_availability()
        assert recommended == "cuda"
        assert devices == ["cpu", "cuda", "mps"]


class TestNativeFilePickerAvailable:
    def test_darwin_is_always_true(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert platform_module._native_file_picker_available() is True

    def test_linux_with_zenity_and_display_is_true(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/zenity")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert platform_module._native_file_picker_available() is True

    def test_linux_without_display_is_false(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/zenity")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert platform_module._native_file_picker_available() is False

    def test_linux_without_zenity_is_false(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setenv("DISPLAY", ":0")
        assert platform_module._native_file_picker_available() is False

    def test_other_platform_is_false(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert platform_module._native_file_picker_available() is False

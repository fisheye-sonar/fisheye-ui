import json

import pytest
from pydantic import ValidationError

from fisheye_ui import telemetry_settings
from fisheye_ui.enums import TelemetryChoice
from fisheye_ui.schemas import TelemetryContact, TelemetrySettings


def _contact():
    return TelemetryContact(
        name="Jane Doe", institution="Caltech", email="jane@example.edu"
    )


class TestTelemetrySettingsModel:
    def test_defaults_to_not_chosen(self):
        assert TelemetrySettings().choice is None

    def test_contact_choice_requires_contact_details(self):
        with pytest.raises(ValidationError):
            TelemetrySettings(choice=TelemetryChoice.CONTACT)

    def test_contact_requires_email_only(self):
        settings = TelemetrySettings(
            choice=TelemetryChoice.CONTACT,
            contact=TelemetryContact(email="jane@example.edu"),
        )
        assert settings.contact.name is None

    @pytest.mark.parametrize(
        "choice", [None, TelemetryChoice.OFF, TelemetryChoice.ANONYMOUS]
    )
    def test_contact_dropped_for_non_contact_choice(self, choice):
        """Switching away from "contact" must never leave contact details
        behind to be sent later."""
        settings = TelemetrySettings(choice=choice, contact=_contact())
        assert settings.contact is None


class TestLoadSave:
    def test_load_without_file_is_not_chosen(self):
        assert telemetry_settings.load() == TelemetrySettings()

    def test_round_trip(self):
        saved = TelemetrySettings(choice=TelemetryChoice.CONTACT, contact=_contact())
        telemetry_settings.save(saved)

        assert telemetry_settings.load() == saved

    def test_switching_to_anonymous_removes_contact_from_disk(self):
        telemetry_settings.save(
            TelemetrySettings(choice=TelemetryChoice.CONTACT, contact=_contact())
        )
        telemetry_settings.save(TelemetrySettings(choice=TelemetryChoice.ANONYMOUS))

        on_disk = telemetry_settings.TELEMETRY_SETTINGS_PATH.read_text()
        assert "jane@example.edu" not in on_disk
        assert telemetry_settings.load().choice == TelemetryChoice.ANONYMOUS

    def test_corrupt_file_falls_back_to_not_chosen(self):
        path = telemetry_settings.TELEMETRY_SETTINGS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")

        assert telemetry_settings.load().choice is None

    def test_invalid_contents_fall_back_to_not_chosen(self):
        """e.g. a hand-edited file with "contact" but no email - must not be
        treated as a sending choice."""
        path = telemetry_settings.TELEMETRY_SETTINGS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"choice": "contact"}))

        assert telemetry_settings.load().choice is None

    def test_save_leaves_no_temp_file(self):
        telemetry_settings.save(TelemetrySettings(choice=TelemetryChoice.OFF))

        siblings = list(telemetry_settings.TELEMETRY_SETTINGS_PATH.parent.iterdir())
        assert siblings == [telemetry_settings.TELEMETRY_SETTINGS_PATH]


class TestTelemetryDisabled:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("FISHEYE_UI_TELEMETRY_ENABLED", raising=False)
        assert telemetry_settings.enabled() is True

    def test_disabled_with_zero(self, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_ENABLED", "0")
        assert telemetry_settings.enabled() is False

    def test_save_refuses_when_disabled(self, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_ENABLED", "0")
        with pytest.raises(telemetry_settings.TelemetryDisabledError):
            telemetry_settings.save(
                TelemetrySettings(choice=TelemetryChoice.CONTACT, contact=_contact())
            )

        assert not telemetry_settings.TELEMETRY_SETTINGS_PATH.exists()

    def test_load_is_off_when_disabled_even_with_saved_choice(self, monkeypatch):
        """A settings file left over from before telemetry was turned off
        must not be treated as a sending choice."""
        telemetry_settings.save(
            TelemetrySettings(choice=TelemetryChoice.CONTACT, contact=_contact())
        )
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_ENABLED", "0")

        loaded = telemetry_settings.load()
        assert loaded.choice == TelemetryChoice.OFF
        assert loaded.contact is None

    def test_platform_reports_flag(self, client, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_ENABLED", "0")
        assert client.get("/platform").json()["telemetry_enabled"] is False

        monkeypatch.delenv("FISHEYE_UI_TELEMETRY_ENABLED")
        assert client.get("/platform").json()["telemetry_enabled"] is True

import pytest

from fisheye_ui import telemetry_settings

CONTACT = {"name": "Jane Doe", "institution": "Caltech", "email": "jane@example.edu"}


class TestGetTelemetrySettings:
    def test_not_chosen_by_default(self, client):
        response = client.get("/settings/telemetry")

        assert response.status_code == 200
        assert response.json() == {"choice": None, "contact": None}

    def test_returns_saved_choice(self, client):
        client.put(
            "/settings/telemetry", json={"choice": "contact", "contact": CONTACT}
        )

        assert client.get("/settings/telemetry").json() == {
            "choice": "contact",
            "contact": CONTACT,
        }

    def test_off_when_disabled(self, client, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_ENABLED", "0")

        assert client.get("/settings/telemetry").json() == {
            "choice": "off",
            "contact": None,
        }


class TestPutTelemetrySettings:
    @pytest.mark.parametrize("choice", ["off", "anonymous"])
    def test_saves_choice(self, client, choice):
        response = client.put("/settings/telemetry", json={"choice": choice})

        assert response.status_code == 200
        assert response.json() == {"choice": choice, "contact": None}
        assert telemetry_settings.load().choice == choice

    def test_saves_contact(self, client):
        response = client.put(
            "/settings/telemetry", json={"choice": "contact", "contact": CONTACT}
        )

        assert response.status_code == 200
        assert response.json() == {"choice": "contact", "contact": CONTACT}

    def test_contact_with_email_only(self, client):
        response = client.put(
            "/settings/telemetry",
            json={"choice": "contact", "contact": {"email": "jane@example.edu"}},
        )

        assert response.status_code == 200
        assert response.json()["contact"] == {
            "name": None,
            "institution": None,
            "email": "jane@example.edu",
        }

    def test_is_idempotent(self, client):
        body = {"choice": "contact", "contact": CONTACT}
        first = client.put("/settings/telemetry", json=body)
        second = client.put("/settings/telemetry", json=body)

        assert first.json() == second.json()

    def test_contact_dropped_for_anonymous(self, client):
        """The response reflects what was actually saved, not what was sent."""
        response = client.put(
            "/settings/telemetry", json={"choice": "anonymous", "contact": CONTACT}
        )

        assert response.status_code == 200
        assert response.json() == {"choice": "anonymous", "contact": None}

    def test_choice_required(self, client):
        """ "Not chosen yet" is only the starting state - clients can't set it."""
        assert client.put("/settings/telemetry", json={}).status_code == 422
        assert (
            client.put("/settings/telemetry", json={"choice": None}).status_code == 422
        )

    def test_unknown_choice_rejected(self, client):
        response = client.put("/settings/telemetry", json={"choice": "sometimes"})

        assert response.status_code == 422

    def test_contact_choice_without_contact_rejected(self, client):
        response = client.put("/settings/telemetry", json={"choice": "contact"})

        assert response.status_code == 422
        assert telemetry_settings.load().choice is None

    def test_contact_without_email_rejected(self, client):
        response = client.put(
            "/settings/telemetry",
            json={"choice": "contact", "contact": {"name": "Jane Doe"}},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "email", ["", "jane", "jane@", "@example.edu", "jane example.edu"]
    )
    def test_invalid_email_rejected(self, client, email):
        response = client.put(
            "/settings/telemetry",
            json={"choice": "contact", "contact": {"email": email}},
        )

        assert response.status_code == 422
        assert telemetry_settings.load().choice is None

    def test_forbidden_when_disabled(self, client, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_ENABLED", "0")
        response = client.put(
            "/settings/telemetry", json={"choice": "contact", "contact": CONTACT}
        )

        assert response.status_code == 403
        assert not telemetry_settings.TELEMETRY_SETTINGS_PATH.exists()

    def test_save_failure_is_reported(self, client, monkeypatch):
        """A choice that didn't save must not look to the user like it did."""

        def fail(settings):
            raise OSError("disk full")

        monkeypatch.setattr(telemetry_settings, "save", fail)
        response = client.put("/settings/telemetry", json={"choice": "anonymous"})

        assert response.status_code == 500

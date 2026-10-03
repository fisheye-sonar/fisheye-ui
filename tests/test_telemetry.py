import json
from datetime import datetime

from fisheye_ui.enums import JobStatus
from fisheye_ui.job_manager import Job, build_telemetry_payload


def _job(**overrides):
    defaults = dict(
        id="job-123",
        status=JobStatus.COMPLETED,
        created_at=datetime(2026, 9, 17, 12, 0, 0),
        finished_at=datetime(2026, 9, 17, 12, 5, 0),
        config={
            "input_path": "/Users/personal_name_here/TMP/klamath_site_7/run.aris",
            "output_dir": "/Users/personal_name_here/TMP/klamath_site_7/out",
            "export_options": ["summary_csv"],
            "upstream_direction": "left",
            "distance_offset": 1.5,
            "platform": {"device": "mps"},
        },
        results=[
            {
                "Source.Name": "2026-09-01_klamath_site_7.aris",
                "file_index": "0",
                "absolute_up": "3",
                "absolute_down": "1",
                "net_count": "2",
            }
        ],
        error=None,
        error_type=None,
        telemetry_events=[],
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestBuildTelemetryPayload:
    def test_never_leaks_input_or_output_path(self):
        job = _job()
        payload = build_telemetry_payload(job)
        serialized = json.dumps(payload.model_dump(), default=str)

        assert "/Users/personal_name_here" not in serialized
        assert "klamath_site_7" not in serialized

    def test_never_leaks_filename(self):
        job = _job()
        payload = build_telemetry_payload(job)
        serialized = json.dumps(payload.model_dump(), default=str)

        assert "2026-09-01_klamath_site_7.aris" not in serialized

    def test_counts_use_file_index_not_filename(self):
        job = _job()
        payload = build_telemetry_payload(job)

        assert len(payload.counts) == 1
        assert payload.counts[0].file_index == 0
        assert payload.counts[0].absolute_up == 3
        assert payload.counts[0].absolute_down == 1
        assert payload.counts[0].net_count == 2

    def test_row_without_file_index_is_dropped_not_guessed(self):
        """A summary CSV row from an older `fisheye` (before the upstream
        per-file-key fix) has no file_index column. It must be left out
        of telemetry entirely, not assigned a guessed position - a wrong
        join between counts and track_stats is worse than a missing row."""
        job = _job(
            results=[
                {
                    "Source.Name": "no_index.aris",
                    "absolute_up": "1",
                    "absolute_down": "0",
                    "net_count": "1",
                }
            ]
        )
        payload = build_telemetry_payload(job)

        assert payload.counts == []

    def test_track_stats_use_file_index_from_event(self):
        job = _job(
            telemetry_events=[
                {
                    "event": "processed_file_stats",
                    "file_index": 0,
                    "num_tracks": 2,
                    "num_counts": 4,
                    "avg_bbox_width_meters": 0.5,
                    "median_bbox_width_meters": 0.48,
                    "std_bbox_width_meters": 0.05,
                }
            ]
        )
        payload = build_telemetry_payload(job)

        assert len(payload.track_stats) == 1
        assert payload.track_stats[0].file_index == 0
        assert payload.track_stats[0].num_tracks == 2

    def test_track_stats_event_without_file_index_is_dropped(self):
        job = _job(
            telemetry_events=[
                {
                    "event": "processed_file_stats",
                    "num_tracks": 2,
                    "num_counts": 4,
                }
            ]
        )
        payload = build_telemetry_payload(job)

        assert payload.track_stats == []

    def test_no_counts_event_is_ignored_not_treated_as_track_stats(self):
        job = _job(
            telemetry_events=[
                {"event": "no_counts", "file_index": 0, "file_path": "/should/not/leak"}
            ]
        )
        payload = build_telemetry_payload(job)

        assert payload.track_stats == []

    def test_error_type_is_class_name_only_not_message(self):
        """job.error (the exception message) frequently embeds the
        failing file's path - the payload must only ever carry the
        exception class name, sourced from job.error_type."""
        job = _job(
            status=JobStatus.FAILED,
            error="[Errno 2] No such file or directory: '/Users/personal_name_here/TMP/secret.aris'",
            error_type="FileNotFoundError",
        )
        payload = build_telemetry_payload(job)

        assert payload.error_type == "FileNotFoundError"
        serialized = json.dumps(payload.model_dump(), default=str)
        assert "secret.aris" not in serialized
        assert "/Users/personal_name_here" not in serialized

    def test_file_count_reflects_results_length_even_without_file_index(self):
        """file_count is a simple count, independent of whether
        individual rows had a usable file_index - it's not sensitive on
        its own and shouldn't be dropped just because per-file joining
        couldn't happen."""
        job = _job(
            results=[
                {"Source.Name": "a.aris", "absolute_up": "1"},
                {"Source.Name": "b.aris", "absolute_up": "2"},
            ]
        )
        payload = build_telemetry_payload(job)

        assert payload.file_count == 2
        assert payload.counts == []  # no file_index on either row

    def test_duration_computed_from_timestamps(self):
        job = _job()
        payload = build_telemetry_payload(job)

        assert payload.duration_seconds == 300.0

    def test_duration_none_when_job_not_finished(self):
        job = _job(finished_at=None, status=JobStatus.RUNNING)
        payload = build_telemetry_payload(job)

        assert payload.duration_seconds is None

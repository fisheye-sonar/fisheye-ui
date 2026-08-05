from pathlib import Path

from fisheye_ui.output_paths import has_existing_predictions, next_available_output_dir


class TestHasExistingPredictions:
    def test_false_when_no_marker_exists(self, tmp_path):
        input_file = tmp_path / "clip.aris"
        input_file.write_text("data")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        assert has_existing_predictions(input_file, output_dir) is False

    def test_true_when_marker_exists_for_single_file(self, tmp_path):
        input_file = tmp_path / "clip.aris"
        input_file.write_text("data")
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        (output_dir / "FCe_clip_ID_.txt").write_text("marker")

        assert has_existing_predictions(input_file, output_dir) is True

    def test_true_when_any_file_in_directory_has_a_marker(self, tmp_path):
        input_dir = tmp_path / "batch"
        input_dir.mkdir()
        (input_dir / "clipA.aris").write_text("data")
        (input_dir / "clipB.aris").write_text("data")
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        (output_dir / "FCe_clipB_ID_.txt").write_text("marker")

        assert has_existing_predictions(input_dir, output_dir) is True

    def test_false_for_directory_with_no_markers(self, tmp_path):
        input_dir = tmp_path / "batch"
        input_dir.mkdir()
        (input_dir / "clipA.aris").write_text("data")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        assert has_existing_predictions(input_dir, output_dir) is False

    def test_false_when_input_path_is_neither_file_nor_dir(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        assert has_existing_predictions(missing, output_dir) is False


class TestNextAvailableOutputDir:
    def test_returns_timestamped_subfolder_under_base_dir(self, tmp_path):
        result = next_available_output_dir(tmp_path)

        assert result.parent == tmp_path
        assert result != tmp_path
        assert isinstance(result, Path)

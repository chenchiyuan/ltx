from gpu_server.worker_adapter.mgpu import dimensions_for_aspect_ratio
from gpu_server.worker_adapter.mgpu import frame_count_for_duration


def test_frame_count_for_duration_returns_8k_plus_one() -> None:
    assert frame_count_for_duration(10, 24) == 241
    assert frame_count_for_duration(1, 24) == 25
    assert frame_count_for_duration(0, 24) == 9


def test_mgpu_dimensions_are_two_stage_compatible() -> None:
    for aspect_ratio in ["16:9", "9:16", "1:1", "4:3", "3:4", "unknown"]:
        width, height = dimensions_for_aspect_ratio(aspect_ratio)
        assert width % 64 == 0
        assert height % 64 == 0

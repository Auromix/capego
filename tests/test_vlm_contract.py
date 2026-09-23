import json

import pytest

from capego.vlm import semantic_annotations


def test_semantic_adapter_owns_ids_and_preserves_uncertainty():
    raw = {"tasks": [{"start_s": 0, "end_s": 2, "description": "Move cup", "operations": [
        {"start_s": .2, "end_s": 1.5, "description": "Right hand moves cup", "hands": ["right"]},
        {"start_s": .3, "end_s": 1.3, "description": "Left hand steadies box", "hands": ["left"]}]}]}
    result = semantic_annotations(json.dumps(raw), 2_000_000_000, ["left_rgb"])
    assert [o.id for o in result.operations] == ["operation-1", "operation-2"]
    assert all(o.task_id == "task-1" and o.needs_review for o in result.operations)
    assert all(o.observation_status == "undetermined" and not o.object_ids for o in result.operations)
    assert not result.objects


@pytest.mark.parametrize("raw", [
    {"tasks": [{"start_s": 0, "end_s": 5, "description": "Outside recording"}]},
    {"tasks": [{"start_s": 0, "end_s": 2, "description": "Task", "operations": [{"start_s": 0, "end_s": 1, "description": "Missing hand"}]}]},
    {"tasks": [{"start_s": 0, "end_s": 2, "description": "Task", "unknown": True}]},
])
def test_invalid_semantic_output_is_not_silently_repaired(raw):
    with pytest.raises(ValueError):
        semantic_annotations(json.dumps(raw), 2_000_000_000, ["left_rgb"])

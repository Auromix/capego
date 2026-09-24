"""Deterministic fixtures for software tests, never real annotations."""

import copy
import math

from ..annotations import AnnotationSet


def synthetic_annotations(rec, times):
    duration = rec["end"]["ended_at_ns"]
    return AnnotationSet.model_validate(
        {
            "tasks": [
                {
                    "id": "task-1",
                    "start_ns": 0,
                    "end_ns": duration,
                    "description": "合成桌面操作测试",
                    "needs_review": False,
                }
            ],
            "operations": [
                {
                    "id": "operation-1",
                    "task_id": "task-1",
                    "start_ns": 0,
                    "end_ns": duration,
                    "description": "合成右手移动杯子，左手位于桌面",
                    "hands": ["right"],
                    "object_ids": ["object-cup"],
                    "action_label": "move",
                    "observation_status": "observed",
                    "needs_review": False,
                }
            ],
            "objects": [
                {
                    "id": "object-cup",
                    "name": "synthetic cup",
                    "view": "left_rgb",
                    "boxes": [
                        {
                            "timestamp_ns": t,
                            "xyxy": [
                                0.24 + 0.12 * math.sin(t / 1e9),
                                0.43,
                                0.36 + 0.12 * math.sin(t / 1e9),
                                0.67,
                            ],
                        }
                        for t in times
                    ],
                }
            ],
        }
    )


def synthetic_geometry(times):
    frames = []
    for t in times:
        seconds = t / 1e9
        hands = {}
        for side, sign in [("left", -1), ("right", 1)]:
            wrist = [sign * 0.18 + 0.04 * math.sin(seconds), 0.1, 0.5]
            joints = [wrist] + [
                [
                    wrist[0] + (finger - 2) * 0.012,
                    wrist[1] - joint * 0.018,
                    wrist[2] + 0.003 * math.sin(seconds + finger),
                ]
                for finger in range(5)
                for joint in range(1, 5)
            ]
            hands[side] = {
                "wrist_pose": wrist + [1.0, 0.0, 0.0, 0.0],
                "wrist_valid": True,
                "joints": joints,
                "joint_valid": [True] * 21,
                "confidence": 1.0,
            }
        # The fixture's local origin is its stationary reference camera, so these
        # two frames coincide. A real backend must apply the measured camera pose.
        frames.append(
            {
                "timestamp_ns": t,
                "camera_pose": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
                "camera_valid": True,
                "hands": hands,
                "hands_camera": copy.deepcopy(hands),
            }
        )
    return {
        "status": "synthetic",
        "frame": "recording_local",
        "reference_camera": "left_rgb",
        "axes": "x_right_y_down_z_forward",
        "length_unit": "m",
        "quaternion_order": "wxyz",
        "pose_direction": "local_from_body",
        "provider": "synthetic-fixture-v1",
        "frames": frames,
        "hand_reference": "wrist",
        "joint_names": [
            "wrist",
            "thumb_cmc",
            "thumb_mcp",
            "thumb_ip",
            "thumb_tip",
            "index_mcp",
            "index_pip",
            "index_dip",
            "index_tip",
            "middle_mcp",
            "middle_pip",
            "middle_dip",
            "middle_tip",
            "ring_mcp",
            "ring_pip",
            "ring_dip",
            "ring_tip",
            "little_mcp",
            "little_pip",
            "little_dip",
            "little_tip",
        ],
        "note": "Synthetic numerical fixtures, not measurements or a hand-estimation model",
    }

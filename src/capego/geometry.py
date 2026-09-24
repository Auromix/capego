"""Metric tracking contract shared by importers and processing adapters."""

from typing import Annotated

from pydantic import Field, model_validator

from .contracts import Contract

Vector3 = Annotated[list[float], Field(min_length=3, max_length=3)]
Pose7 = Annotated[list[float], Field(min_length=7, max_length=7)]
JOINT_NAMES = ["wrist", "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip"] + [
    f"{finger}_{joint}"
    for finger in ("index", "middle", "ring", "little")
    for joint in ("mcp", "pip", "dip", "tip")
]


def check_pose(pose, valid):
    if valid != (pose is not None):
        raise ValueError("Invalid poses must be null; valid poses must be present")
    if pose is not None and abs(sum(x * x for x in pose[3:]) - 1) > 0.002:
        raise ValueError("Pose quaternion must be normalized wxyz")


class HandFrame(Contract):
    wrist_pose: Pose7 | None
    wrist_valid: bool
    joints: list[Vector3 | None] = Field(min_length=21, max_length=21)
    joint_valid: list[bool] = Field(min_length=21, max_length=21)
    confidence: float | None = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validity(self):
        check_pose(self.wrist_pose, self.wrist_valid)
        if any(v != (p is not None) for p, v in zip(self.joints, self.joint_valid, strict=True)):
            raise ValueError("Joint validity must match null/present observations")
        return self


class TrackingFrame(Contract):
    timestamp_ns: int = Field(ge=0)
    camera_pose: Pose7 | None
    camera_valid: bool
    hands: dict[str, HandFrame]
    hands_camera: dict[str, HandFrame]

    @model_validator(mode="after")
    def validity(self):
        check_pose(self.camera_pose, self.camera_valid)
        for hands in (self.hands, self.hands_camera):
            if set(hands) != {"left", "right"}:
                raise ValueError("Tracking requires explicit left and right entries")
        for side in ("left", "right"):
            a, b = self.hands[side], self.hands_camera[side]
            if a.wrist_valid != b.wrist_valid or a.joint_valid != b.joint_valid:
                raise ValueError("Coordinate representations must share validity masks")
        if not self.camera_valid and any(
            h.wrist_valid or any(h.joint_valid) for h in self.hands_camera.values()
        ):
            raise ValueError("Camera-relative observations require a valid camera pose")
        return self

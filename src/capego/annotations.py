"""Validated annotation contract; missing geometry stays missing."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Identifier


class Span(Contract):
    id: Identifier
    start_ns: int = Field(ge=0)
    end_ns: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=4000)
    needs_review: bool = True

    @model_validator(mode="after")
    def interval(self):
        if self.end_ns <= self.start_ns:
            raise ValueError("Intervals must be nonempty and half-open")
        return self


class Task(Span):
    pass


class Operation(Span):
    task_id: Identifier
    hands: list[Literal["left", "right"]] = Field(min_length=1, max_length=2)
    object_ids: list[Identifier] = Field(default_factory=list)
    action_label: str | None = None
    observation_status: Literal["observed", "undetermined"] = "undetermined"


class ObjectBox(Contract):
    timestamp_ns: int = Field(ge=0)
    xyxy: list[float] = Field(min_length=4, max_length=4)
    valid: bool = True

    @model_validator(mode="after")
    def rectangle(self):
        x1, y1, x2, y2 = self.xyxy
        if not 0 <= x1 < x2 <= 1 or not 0 <= y1 < y2 <= 1:
            raise ValueError("Boxes are normalized xyxy in [0,1]")
        return self


class ObjectTrack(Contract):
    id: Identifier
    name: str = Field(min_length=1, max_length=200)
    view: Identifier
    boxes: list[ObjectBox] = Field(default_factory=list)


class AnnotationSet(Contract):
    tasks: list[Task]
    operations: list[Operation]
    objects: list[ObjectTrack] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        all_ids = [x.id for x in [*self.tasks, *self.operations, *self.objects]]
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("Annotation IDs must be unique within a processing version")
        tasks = {x.id: x for x in self.tasks}
        objects = {x.id for x in self.objects}
        for op in self.operations:
            task = tasks.get(op.task_id)
            if not task or op.start_ns < task.start_ns or op.end_ns > task.end_ns:
                raise ValueError("Operation must be contained in its task")
            if not set(op.object_ids) <= objects:
                raise ValueError("Unknown related object ID")
            if len(set(op.hands)) != len(op.hands) or len(set(op.object_ids)) != len(op.object_ids):
                raise ValueError("Duplicate hands or object IDs")
        return self

    def validate_duration(self, duration_ns, views):
        for span in [*self.tasks, *self.operations]:
            if span.end_ns > duration_ns:
                raise ValueError("Annotation exceeds recording duration")
        for track in self.objects:
            if track.view not in views or any(b.timestamp_ns >= duration_ns for b in track.boxes):
                raise ValueError("Object box has unknown view or out-of-range time")
        return self

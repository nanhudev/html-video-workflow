"""Runtime data structures: Job ▸ Task ▸ Step ▸ Artifact."""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SKIPPED = "skipped"
    CACHED = "cached"
    COMPLETED = "completed"
    FAILED = "failed"


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


class Artifact(_Base):
    name: str
    path: str
    kind: str = "file"
    sha256: str | None = None
    size_bytes: int | None = None
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    metadata: dict[str, Any] = Field(default_factory=dict)


class Step(_Base):
    id: str
    name: str
    status: StepStatus = StepStatus.PENDING
    provider: str | None = None
    fallback_from: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    progress: float = 0.0
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    error: str | None = None
    error_type: str | None = None
    notes: list[str] = Field(default_factory=list)

    def start(self, provider: str | None = None) -> None:
        self.status = StepStatus.RUNNING
        self.provider = provider
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.progress = 0.01

    def finish(self, status: StepStatus = StepStatus.COMPLETED) -> None:
        self.status = status
        self.ended_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.progress = 1.0 if status != StepStatus.FAILED else self.progress

    def fail(self, message: str, error_type: str | None = None) -> None:
        self.status = StepStatus.FAILED
        self.error = message
        self.error_type = error_type
        self.ended_at = time.strftime("%Y-%m-%dT%H:%M:%S")


class Task(_Base):
    id: str
    name: str
    stage: str
    steps: list[Step] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        return sum(step.progress for step in self.steps) / len(self.steps)


class JobPlan(_Base):
    preset: str = "auto"
    llm: str | None = None
    tts: str | None = None
    renderer: str | None = None
    subtitle: str | None = None
    reasons: dict[str, list[str]] = Field(default_factory=dict)
    candidates: list[dict[str, Any]] = Field(default_factory=list)

    # ---- product-level facts, so a polled result can answer every question a
    # ---- synchronous one answers. `job_result()` promises "the same shape",
    # ---- and for a while it was not: an async caller saw empty template,
    # ---- style, scenes and elapsed time, which reads as "the render lost my
    # ---- settings" rather than "the polling response was thinner".
    template: str | None = None
    style: str | None = None
    scenes: int = 0
    title: str = ""
    duration_sec: float | None = None
    narration_source: str | None = None
    writing_preset: str | None = None
    #: The planner's flat "why this" list. Distinct from ``reasons`` above,
    #: which is the router's per-stage explanation keyed by stage name.
    plan_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Job(_Base):
    id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")
    project_id: str
    status: JobStatus = JobStatus.QUEUED
    preset: str = "auto"
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    updated_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    started_at: str | None = None
    ended_at: str | None = None
    plan: JobPlan = Field(default_factory=JobPlan)
    tasks: list[Task] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    errors: list[dict[str, str]] = Field(default_factory=list)
    fallbacks: list[dict[str, str]] = Field(default_factory=list)
    quality: dict[str, Any] | None = None

    # ------------------------------------------------------------- helpers
    @property
    def progress(self) -> float:
        if not self.tasks:
            return 0.0
        return sum(task.progress for task in self.tasks) / len(self.tasks)

    def touch(self) -> None:
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def add_task(self, name: str, stage: str) -> Task:
        task = Task(id=f"task_{uuid.uuid4().hex[:8]}", name=name, stage=stage)
        self.tasks.append(task)
        return task

    def find_task(self, stage: str) -> Task | None:
        for task in self.tasks:
            if task.stage == stage:
                return task
        return None

    def all_steps(self) -> list[Step]:
        return [step for task in self.tasks for step in task.steps]


def new_step(name: str, **kwargs: Any) -> Step:
    return Step(id=f"step_{uuid.uuid4().hex[:8]}", name=name, **kwargs)

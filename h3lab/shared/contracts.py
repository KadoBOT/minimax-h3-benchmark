"""Strict public models for the pinned ComfyUI SDUI service contract."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


Identifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
]
ComponentId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,127}$")]
Binding = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")]
Capability = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,127}$")]
OpaqueId = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
            r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
        )
    ),
]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
StableIdentifier = Identifier
Primitive: TypeAlias = str | int | float | bool | None
OptionValue: TypeAlias = str | int | float | bool


def _safe_api_path(value: str) -> str:
    parts = urlsplit(value)
    segments = re.split(r"[/?#]", value)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or "%2e" in value.lower()
        or ".." in segments
        or parts.scheme
        or parts.netloc
    ):
        raise ValueError("must be a safe API-relative path")
    return value


ApiPath = Annotated[str, AfterValidator(_safe_api_path)]


def _safe_json(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                not key
                or len(key) > 256
                or key in {"__proto__", "prototype", "constructor"}
            ):
                raise ValueError("input contains an unsafe object key")
            _safe_json(item)
    elif isinstance(value, list):
        for item in value:
            _safe_json(item)
    return value


class AvailabilityReason(ContractModel):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    detail: Annotated[str, Field(min_length=1, max_length=2000)]
    retryable: bool


class Available(ContractModel):
    state: Literal["available"]
    observed_at: datetime


class Unavailable(ContractModel):
    state: Literal["disabled", "incompatible"]
    observed_at: datetime
    reason: AvailabilityReason


Availability: TypeAlias = Annotated[
    Available | Unavailable, Field(discriminator="state")
]


class Predicate(ContractModel):
    field: Binding
    operator: Literal["equals", "not_equals", "in"]
    value: Primitive | list[Primitive]

    @model_validator(mode="after")
    def valid_operator_value(self) -> Predicate:
        is_list = isinstance(self.value, list)
        if self.operator == "in" and (not is_list or not self.value):
            raise ValueError("an in predicate requires a non-empty array")
        if self.operator != "in" and is_list:
            raise ValueError("an equality predicate requires a scalar")
        return self


class Component(ContractModel):
    id: ComponentId
    optional: bool = False


class InputComponent(Component):
    binding: Binding
    label: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    required: bool
    visible_when: Annotated[list[Predicate], Field(min_length=1)] | None = None


class SectionComponent(Component):
    kind: Literal["section"]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(min_length=1, max_length=2000)] | None = None


class TextComponent(InputComponent):
    kind: Literal["text"]
    default_value: str | None = None
    placeholder: Annotated[str, Field(max_length=500)] | None = None
    min_length: Annotated[int, Field(ge=0)] | None = None
    max_length: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def valid_lengths(self) -> TextComponent:
        _check_text_lengths(self)
        return self


class TextareaComponent(InputComponent):
    kind: Literal["textarea"]
    default_value: str | None = None
    placeholder: Annotated[str, Field(max_length=500)] | None = None
    min_length: Annotated[int, Field(ge=0)] | None = None
    max_length: Annotated[int, Field(ge=1)] | None = None
    rows: Annotated[int, Field(ge=2, le=40)] | None = None

    @model_validator(mode="after")
    def valid_lengths(self) -> TextareaComponent:
        _check_text_lengths(self)
        return self


class NumberComponent(InputComponent):
    kind: Literal["number"]
    minimum: float | None = None
    maximum: float | None = None
    step: Annotated[float, Field(gt=0)] | None = None
    integer: bool = False
    default_value: float | None = None
    unit: Annotated[str, Field(min_length=1, max_length=40)] | None = None

    @model_validator(mode="after")
    def valid_number(self) -> NumberComponent:
        _check_bounds(self.minimum, self.maximum, self.default_value)
        if (
            self.integer
            and self.default_value is not None
            and not self.default_value.is_integer()
        ):
            raise ValueError("default value must be an integer")
        return self


class SelectOption(ContractModel):
    value: OptionValue
    label: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    disabled: bool = False


class SelectComponent(InputComponent):
    kind: Literal["select"]
    options: Annotated[list[SelectOption], Field(min_length=1)]
    default_value: OptionValue | None = None

    @model_validator(mode="after")
    def valid_options(self) -> SelectComponent:
        keys = [json_scalar_key(option.value) for option in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError("option values must be unique")
        if (
            self.default_value is not None
            and json_scalar_key(self.default_value) not in keys
        ):
            raise ValueError("default value must match an option")
        return self


class ToggleComponent(InputComponent):
    kind: Literal["toggle"]
    default_value: bool


class AssetComponent(InputComponent):
    kind: Literal["asset"]
    accept: Annotated[list[Literal["image", "video", "audio"]], Field(min_length=1)]
    minimum_items: Annotated[int, Field(ge=0)] = 0
    maximum_items: Annotated[int, Field(ge=1, le=32)]

    @model_validator(mode="after")
    def valid_counts(self) -> AssetComponent:
        if len(set(self.accept)) != len(self.accept):
            raise ValueError("accepted asset kinds must be unique")
        if self.minimum_items > self.maximum_items:
            raise ValueError("minimum items cannot exceed maximum items")
        if self.required and self.minimum_items == 0:
            raise ValueError("a required asset must require at least one item")
        return self


class SeedComponent(InputComponent):
    kind: Literal["seed"]
    allow_random: bool
    minimum: Annotated[int, Field(ge=0)]
    maximum: Annotated[int, Field(ge=0, le=9007199254740991)]
    default_value: Annotated[int, Field(ge=0, le=9007199254740991)] | None

    @model_validator(mode="after")
    def valid_seed(self) -> SeedComponent:
        _check_bounds(self.minimum, self.maximum, self.default_value)
        if self.default_value is None and not self.allow_random:
            raise ValueError("a null seed requires random support")
        return self


GenerationComponent: TypeAlias = Annotated[
    SectionComponent
    | TextComponent
    | TextareaComponent
    | NumberComponent
    | SelectComponent
    | ToggleComponent
    | AssetComponent
    | SeedComponent,
    Field(discriminator="kind"),
]


class StatusComponent(Component):
    kind: Literal["status"]
    state: Literal[
        "accepted",
        "queued",
        "running",
        "cancelling",
        "collecting",
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "collection_failed",
    ]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    detail: Annotated[str, Field(min_length=1, max_length=2000)] | None = None


class ProgressComponent(Component):
    kind: Literal["progress"]
    value: Annotated[float, Field(ge=0, le=1)]
    label: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    current: Annotated[int, Field(ge=0)] | None = None
    total: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def valid_progress(self) -> ProgressComponent:
        if (
            self.current is not None
            and self.total is not None
            and self.current > self.total
        ):
            raise ValueError("current progress cannot exceed total")
        return self


class LogEntry(ContractModel):
    sequence: Annotated[int, Field(ge=0)]
    at: datetime
    level: Literal["debug", "info", "warning", "error"]
    message: Annotated[str, Field(min_length=1, max_length=8000)]


class LogComponent(Component):
    kind: Literal["log"]
    entries: Annotated[list[LogEntry], Field(max_length=1000)]


class PreviewComponent(Component):
    kind: Literal["preview"]
    src: ApiPath
    mime: Annotated[str, StringConstraints(pattern=r"^(image|video)/[a-z0-9.+-]+$")]
    sequence: Annotated[int, Field(ge=0)]


class VideoComponent(Component):
    kind: Literal["video"]
    src: ApiPath
    mime: Annotated[str, StringConstraints(pattern=r"^video/[a-z0-9.+-]+$")]
    poster: ApiPath | None = None


class DownloadComponent(Component):
    kind: Literal["download"]
    href: ApiPath
    filename: Annotated[str, Field(min_length=1, max_length=240)]
    label: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("must be a filename")
        return value


JobComponent: TypeAlias = Annotated[
    SectionComponent
    | StatusComponent
    | ProgressComponent
    | LogComponent
    | PreviewComponent
    | VideoComponent
    | DownloadComponent,
    Field(discriminator="kind"),
]


class Action(ContractModel):
    id: ComponentId
    label: Annotated[str, Field(min_length=1, max_length=200)]
    endpoint: ApiPath
    optional: bool = False


class SubmitAction(Action):
    kind: Literal["submit"]
    method: Literal["POST"]


class CancelAction(Action):
    kind: Literal["cancel"]
    method: Literal["POST"]


class DeleteAction(Action):
    kind: Literal["delete"]
    method: Literal["DELETE"]


class RetryCollectionAction(Action):
    kind: Literal["retry_collection"]
    method: Literal["POST"]


JobAction: TypeAlias = Annotated[
    CancelAction | DeleteAction | RetryCollectionAction,
    Field(discriminator="kind"),
]


class Capabilities(ContractModel):
    required: list[Capability]
    optional: list[Capability]

    @model_validator(mode="after")
    def unique_capabilities(self) -> Capabilities:
        if len(self.required) != len(set(self.required)):
            raise ValueError("required capabilities must be unique")
        if len(self.optional) != len(set(self.optional)):
            raise ValueError("optional capabilities must be unique")
        if set(self.required) & set(self.optional):
            raise ValueError("required and optional capabilities must be disjoint")
        return self


class Document(ContractModel):
    protocol_version: Literal["1.0"]
    document_id: Identifier
    schema_revision: StableIdentifier
    workflow_id: StableIdentifier
    workflow_revision: Digest
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    availability: Availability
    capabilities: Capabilities


class GenerationDocument(Document):
    kind: Literal["generation"] = "generation"
    components: Annotated[list[GenerationComponent], Field(min_length=1)]
    actions: Annotated[list[SubmitAction], Field(min_length=1)]

    @model_validator(mode="after")
    def valid_document(self) -> GenerationDocument:
        _validate_document(self.components, self.actions, self.capabilities)
        return self


class JobDocument(Document):
    kind: Literal["job"]
    job_id: OpaqueId
    components: Annotated[list[JobComponent], Field(min_length=1)]
    actions: list[JobAction]

    @model_validator(mode="after")
    def valid_document(self) -> JobDocument:
        _validate_document(self.components, self.actions, self.capabilities)
        return self


class JobSubmission(ContractModel):
    workflow_revision: Digest
    schema_revision: StableIdentifier
    input: dict[Annotated[str, Field(min_length=1, max_length=256)], JsonValue]

    @field_validator("input")
    @classmethod
    def safe_input(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _safe_json(value)
        return value


class CompilerIdentity(ContractModel):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,127}$")]
    version: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
    ]


class PublicJobProvenance(ContractModel):
    manifest_digest: Digest | None = None
    compiler: CompilerIdentity | None = None
    catalog_revision: Digest | None = None
    input_digest: Digest | None = None
    resolved_seed: Annotated[int, Field(ge=0, le=9007199254740991)] | None = None


class PublicJobFailure(ContractModel):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    detail: Annotated[str, Field(min_length=1, max_length=2000)]
    retryable: bool


class PublicJobArtifact(ContractModel):
    id: OpaqueId
    mime: Annotated[str, StringConstraints(pattern=r"^video/[a-z0-9.+-]+$")]
    size: Annotated[int, Field(gt=0, le=9007199254740991)]
    filename: Annotated[str, Field(min_length=1, max_length=240)]
    content_url: ApiPath

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if (
            value in {".", ".."}
            or "/" in value
            or "\\" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("artifact filename must be a safe leaf name")
        return value


class PublicJobLinks(ContractModel):
    self: ApiPath
    view: ApiPath
    events: ApiPath
    preview: ApiPath | None = None
    cancel: ApiPath | None = None
    retry_collection: ApiPath | None = None


class PublicJob(ContractModel):
    id: OpaqueId
    workflow_id: StableIdentifier
    workflow_revision: Digest
    schema_revision: StableIdentifier
    state: Literal[
        "accepted",
        "queued",
        "running",
        "cancelling",
        "collecting",
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "collection_failed",
    ]
    version: Annotated[int, Field(ge=0, le=9007199254740991)]
    created_at: datetime
    updated_at: datetime
    provenance: PublicJobProvenance | None = None
    failure: PublicJobFailure | None = None
    artifact: PublicJobArtifact | None = None
    links: PublicJobLinks

    @model_validator(mode="after")
    def linked_paths_match_identity(self) -> PublicJob:
        if self.artifact is not None:
            upstream = f"/v1/artifacts/{self.artifact.id}/content"
            local = self.artifact.content_url.startswith("/api/runs/") and (
                self.artifact.content_url.endswith("/shared-video")
            )
            if self.artifact.content_url != upstream and not local:
                raise ValueError(
                    "artifact content link does not match artifact identity"
                )
        return self


class PublicJobEvent(ContractModel):
    job_id: OpaqueId
    sequence: Annotated[int, Field(gt=0, le=9007199254740991)]
    type: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,127}$")]
    at: datetime
    data: dict[Annotated[str, Field(min_length=1, max_length=256)], JsonValue]

    @field_validator("data")
    @classmethod
    def safe_data(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _safe_json(value)
        return value


class PublicMediaMetadata(ContractModel):
    id: OpaqueId
    kind: Literal["asset", "artifact"]
    media_kind: Literal["image", "video", "audio"]
    mime: Annotated[str, Field(min_length=1, max_length=200)]
    size: Annotated[int, Field(gt=0, le=9007199254740991)]
    digest: Digest
    filename: Annotated[str, Field(min_length=1, max_length=1000)]
    content_url: ApiPath


class FieldError(ContractModel):
    field: Annotated[str, Field(min_length=1, max_length=200)]
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    detail: Annotated[str, Field(min_length=1, max_length=2000)]


class Problem(ContractModel):
    type: str
    title: Annotated[str, Field(min_length=1, max_length=200)]
    status: Annotated[int, Field(ge=400, le=599)]
    detail: Annotated[str, Field(min_length=1, max_length=4000)] | None = None
    instance: ApiPath | None = None
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    retryable: bool
    request_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    errors: Annotated[list[FieldError], Field(min_length=1, max_length=100)] | None = (
        None
    )

    @field_validator("type")
    @classmethod
    def absolute_type_uri(cls, value: str) -> str:
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            raise ValueError("must be an absolute URI")
        return value


def _check_text_lengths(value: TextComponent | TextareaComponent) -> None:
    if (
        value.min_length is not None
        and value.max_length is not None
        and value.min_length > value.max_length
    ):
        raise ValueError("minimum length cannot exceed maximum length")
    if value.default_value is not None:
        if value.min_length is not None and len(value.default_value) < value.min_length:
            raise ValueError("default text is shorter than minimum")
        if value.max_length is not None and len(value.default_value) > value.max_length:
            raise ValueError("default text is longer than maximum")


def _check_bounds(
    minimum: float | None,
    maximum: float | None,
    default: float | None,
) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("minimum cannot exceed maximum")
    if default is not None:
        if minimum is not None and default < minimum:
            raise ValueError("default value is below minimum")
        if maximum is not None and default > maximum:
            raise ValueError("default value is above maximum")


def json_scalar_key(value: OptionValue) -> tuple[type[Any], OptionValue]:
    return type(value), value


def _validate_document(
    components: list[Any],
    actions: list[Any],
    capabilities: Capabilities,
) -> None:
    ids = [item.id for item in [*components, *actions]]
    if len(ids) != len(set(ids)):
        raise ValueError("component and action ids must be unique")
    bindings = [item.binding for item in components if isinstance(item, InputComponent)]
    if len(bindings) != len(set(bindings)):
        raise ValueError("input bindings must be unique")
    known_bindings = set(bindings)
    for component in components:
        if isinstance(component, InputComponent):
            for predicate in component.visible_when or []:
                if predicate.field not in known_bindings:
                    raise ValueError(
                        "visibility predicate references an unknown binding"
                    )
    required = set(capabilities.required)
    optional = set(capabilities.optional)
    for prefix, item in [
        *(("component", component) for component in components),
        *(("action", action) for action in actions),
    ]:
        if item.kind == "section":
            continue
        capability = f"{prefix}.{item.kind}"
        expected = optional if item.optional else required
        if capability not in expected:
            raise ValueError(f"missing declared capability {capability}")

"""What the installed ComfyUI says its nodes take.

`/object_info` is the only authority on a node's inputs: a custom node pack can rename a
widget between two `git pull`s, and a workflow saved before the rename still carries the old
name. Reading the schema lets the lab notice that before ComfyUI rejects a whole prompt, and
lets it write widgets by name instead of by position.

The lab must also work with ComfyUI switched off — for tests, for `h3lab check`, for building
a prompt to look at. So every lookup falls back: what the saved node declares, then the
snapshot in `nodes.py`, then nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from h3lab.comfy import nodes as N
from h3lab.comfy.workflow import Prompt, declared_widget_names, is_link

# Inputs whose combo list is the contents of ComfyUI's input folder. A run uploads its media
# as part of submitting, so a name that is not there yet is not a problem worth reporting.
_UPLOADED = frozenset({"image", "audio", "file", "video"})

_WIDGET_TYPES = frozenset({"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"})


@dataclass(frozen=True, slots=True)
class WidgetSpec:
    """One widget as `/object_info` describes it: type, range, options, tooltip."""

    name: str
    kind: str
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    tooltip: str = ""
    multiline: bool = False
    options: tuple[str, ...] = ()
    label_on: str = "on"
    label_off: str = "off"


@dataclass(frozen=True, slots=True)
class NodeSchema:
    """One node class as the running ComfyUI describes it."""

    class_type: str
    widget_names: tuple[str, ...] = ()
    input_names: frozenset[str] = frozenset()
    required: frozenset[str] = frozenset()
    combos: dict[str, tuple[str, ...]] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    specs: dict[str, WidgetSpec] = field(default_factory=dict)
    output_types: tuple[str, ...] = ()

    def knows(self, name: str) -> bool:
        """Does this class have an input called *name*?

        A dotted name is a dynamic input the node grew at runtime — `ref_images.ref_image_0`
        on the reference conditioning, `resize_type.scale` on the upscaler. The prefix is
        the declared input; the suffix is the editor's business.
        """
        if name in self.input_names:
            return True
        head = name.split(".", 1)[0]
        return head in self.input_names


def _is_widget(spec: Any) -> bool:
    if not isinstance(spec, (list, tuple)) or not spec:
        return False
    kind = spec[0]
    if isinstance(kind, (list, dict)):
        return True
    if isinstance(kind, str):
        return kind in _WIDGET_TYPES or kind.startswith("COMFY_")
    return False


def _combo_values(spec: Any) -> tuple[str, ...]:
    if not isinstance(spec, (list, tuple)) or not spec:
        return ()
    kind = spec[0]
    if isinstance(kind, list):
        return tuple(str(value) for value in kind if isinstance(value, (str, int, float)))
    options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    values = options.get("options")
    if isinstance(values, list):
        return tuple(
            str(value["key"] if isinstance(value, dict) and "key" in value else value)
            for value in values
        )
    return ()


def _default_value(spec: Any, combo: tuple[str, ...]) -> Any:
    options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if "default" in options:
        return options["default"]
    return combo[0] if combo else None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def widget_spec(name: str, spec: Any) -> WidgetSpec | None:
    """Turn one `/object_info` input entry into a widget description, or None if it is a link."""
    if not _is_widget(spec):
        return None
    kind = spec[0]
    extra = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    options = _combo_values(spec)
    if isinstance(kind, list) or options:
        kind_name = "COMBO"
    else:
        kind_name = str(kind)
    default = _default_value(spec, options)
    return WidgetSpec(
        name=name,
        kind=kind_name,
        default=default,
        minimum=_as_number(extra.get("min")),
        maximum=_as_number(extra.get("max")),
        step=_as_number(extra.get("step")),
        tooltip=str(extra.get("tooltip") or ""),
        multiline=bool(extra.get("multiline")),
        options=options,
        label_on=str(extra.get("label_on") or "on"),
        label_off=str(extra.get("label_off") or "off"),
    )


def parse_schema(class_type: str, info: dict[str, Any]) -> NodeSchema:
    inputs = info.get("input") or {}
    order = info.get("input_order") or {}
    names: list[str] = []
    widgets: list[str] = []
    required: list[str] = []
    combos: dict[str, tuple[str, ...]] = {}
    defaults: dict[str, Any] = {}
    specs: dict[str, WidgetSpec] = {}
    for section in ("required", "optional"):
        entries = inputs.get(section)
        if not isinstance(entries, dict):
            continue
        ordered = [name for name in (order.get(section) or entries) if name in entries]
        for name in ordered:
            spec = entries[name]
            names.append(name)
            if section == "required":
                required.append(name)
            parsed = widget_spec(name, spec)
            if parsed is None:
                continue
            widgets.append(name)
            specs[name] = parsed
            if parsed.options:
                combos[name] = parsed.options
            if parsed.default is not None:
                defaults[name] = parsed.default
    return NodeSchema(
        class_type=class_type,
        widget_names=tuple(widgets),
        input_names=frozenset(names),
        required=frozenset(required),
        combos=combos,
        defaults=defaults,
        specs=specs,
        output_types=tuple(str(value) for value in info.get("output") or ()),
    )


class Schemas:
    """Every installed node class, or nothing at all when ComfyUI is not running."""

    def __init__(self, info: dict[str, Any] | None = None) -> None:
        self._schemas: dict[str, NodeSchema] = {}
        for class_type, entry in (info or {}).items():
            if isinstance(entry, dict):
                self._schemas[str(class_type)] = parse_schema(str(class_type), entry)

    def __bool__(self) -> bool:
        return bool(self._schemas)

    def __len__(self) -> int:
        return len(self._schemas)

    @classmethod
    def from_client(cls, client: Any) -> Schemas:
        """Read the live schemas, or come back empty if ComfyUI cannot be reached."""
        try:
            return cls(client.object_info_all())
        except Exception:  # noqa: BLE001 - a schema read must never fail a run
            return cls()

    def get(self, class_type: str) -> NodeSchema | None:
        return self._schemas.get(class_type)

    def known(self, class_type: str) -> bool:
        return class_type in self._schemas

    def combo(self, class_type: str, input_name: str) -> tuple[str, ...]:
        schema = self.get(class_type)
        return schema.combos.get(input_name, ()) if schema else ()

    def widget_names(self, class_type: str, node: dict[str, Any]) -> Sequence[str] | None:
        """The widget order for one saved node.

        What the node declares wins: it is the only source that knows how this node's
        dynamic combos were expanded when the file was saved. The live schema answers for
        nodes that declare nothing, and the snapshot answers when ComfyUI is not running.
        """
        declared = declared_widget_names(node)
        if declared:
            return declared
        schema = self.get(class_type)
        if schema and schema.widget_names:
            return schema.widget_names
        return N.WIDGET_ORDER.get(class_type)

    def input_names(self, class_type: str) -> frozenset[str]:
        schema = self.get(class_type)
        if schema:
            return schema.input_names
        return frozenset(N.WIDGET_ORDER.get(class_type) or ())

    def accepts(self, class_type: str, name: str, *, unknown_ok: bool = True) -> bool:
        """Would this class accept an input called *name*?"""
        schema = self.get(class_type)
        if schema is None:
            return unknown_ok
        return schema.knows(name)

    def output_type(self, class_type: str, slot: int) -> str:
        schema = self.get(class_type)
        if schema and slot < len(schema.output_types):
            return schema.output_types[slot]
        return ""

    def fill_defaults(self, prompt: Prompt) -> list[str]:
        """Give every required widget the node's own default when the template has none.

        A node pack that adds a widget breaks every workflow saved before it — ComfyUI
        rejects the prompt for a value the author never had the chance to set. The node
        already ships the answer it wants; using it turns a rejection into a run.
        """
        filled: list[str] = []
        for node_id, node in prompt.items():
            schema = self.get(str(node.get("class_type") or ""))
            if schema is None:
                continue
            inputs = node.setdefault("inputs", {})
            for name in schema.required:
                if name in inputs or name not in schema.defaults:
                    continue
                if any(key.startswith(f"{name}.") for key in inputs):
                    continue
                inputs[name] = schema.defaults[name]
                filled.append(f"{node_id}.{name}={schema.defaults[name]!r}")
        return sorted(filled)

    # --- validation --------------------------------------------------------

    def problems(self, prompt: Prompt, *, skip: Iterable[str] = ()) -> list[str]:
        """Everything the installed ComfyUI would reject, without asking it to.

        Silence here is not proof — an empty schema set means we could not ask. What is
        reported is exact: a class that is not installed, a required input that nothing
        supplies, a file that is not on disk.
        """
        if not self._schemas:
            return []
        skipped = set(skip)
        found: list[str] = []
        for node_id, node in sorted(prompt.items()):
            class_type = str(node.get("class_type") or "")
            if class_type in skipped:
                continue
            schema = self.get(class_type)
            if schema is None:
                found.append(f"{node_id}: ComfyUI has no node class {class_type!r}")
                continue
            inputs = node.get("inputs") or {}
            for name in sorted(schema.required):
                if name not in inputs and not any(
                    key.startswith(f"{name}.") for key in inputs
                ):
                    found.append(f"{node_id} ({class_type}): missing required input {name!r}")
            for name, value in sorted(inputs.items()):
                if is_link(value) or name in _UPLOADED or not schema.knows(name):
                    continue
                options = schema.combos.get(name)
                if options and isinstance(value, str) and value not in options:
                    found.append(
                        f"{node_id} ({class_type}): {name}={value!r} is not installed"
                    )
        return found

    def notes(self, prompt: Prompt) -> list[str]:
        """Inputs the installed node does not declare.

        Worth showing and not worth failing on: a node whose widget set depends on another
        widget (`VHS_VideoCombine` grows `crf` once a format is chosen) carries inputs no
        schema mentions, and ComfyUI ignores what it does not recognise. A name here that
        the lab *meant* to set is the interesting case — a renamed widget looks like this.
        """
        if not self._schemas:
            return []
        found: list[str] = []
        for node_id, node in sorted(prompt.items()):
            schema = self.get(str(node.get("class_type") or ""))
            if schema is None:
                continue
            for name in sorted(node.get("inputs") or {}):
                if not schema.knows(name):
                    found.append(f"{node_id} ({schema.class_type}): unknown input {name!r}")
        return found


def static_schemas() -> Schemas:
    """No live truth available. Every lookup falls back to the saved node and the snapshot."""
    return Schemas()


class SchemaCache:
    """The installed node descriptions, read once and re-read when something proves stale.

    `/object_info` is a megabyte of JSON describing every installed class, so it is read on
    first use and kept. It is not polled: node packs only change when ComfyUI restarts, and
    the symptom of having missed that is a rejected prompt — which is exactly when the runner
    drops this cache. A read that fails leaves the cache empty rather than raising, because a
    lab that cannot reach ComfyUI must still be able to build and inspect a graph.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._schemas: Schemas | None = None

    def get(self) -> Schemas:
        with self._lock:
            if self._schemas is None:
                self._schemas = Schemas.from_client(self._client)
            return self._schemas

    def invalidate(self) -> None:
        with self._lock:
            self._schemas = None

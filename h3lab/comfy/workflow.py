"""Reading a saved ComfyUI workflow into the flat graph the API speaks.

The editor format keeps moving: nodes get renumbered, a whole pipeline can be folded into a
subgraph, links are written as arrays in one version and as objects in the next. Everything
in this module exists so the rest of the lab never has to know which shape it was handed.

A subgraph is flattened the way ComfyUI's own executor flattens it — an inner node becomes
`instance:local` (`169:23`) — so ids in our prompts, our progress events and ComfyUI's own
logs are the same ids. Promoted widgets and boundary links are resolved while flattening,
which is why nothing downstream ever sees a link that crosses a subgraph edge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

from h3lab.comfy import nodes as N

Prompt = dict[str, dict[str, Any]]
WidgetNames = Callable[[str, dict[str, Any]], Sequence[str] | None]

_MISSING = object()

# Reroute is layout sugar: it never executes, so links through it are resolved to whatever
# feeds the reroute.
_PASS_THROUGH_TYPES = frozenset({"Reroute"})


@dataclass(slots=True)
class Node:
    """One executable node, addressed the way ComfyUI's executor addresses it."""

    id: str
    class_type: str
    inputs: dict[str, Any]
    title: str = ""
    mode: int = 0
    input_types: dict[str, str] = field(default_factory=dict)
    output_types: tuple[str, ...] = ()
    path: tuple[int, ...] = ()
    local_id: int = 0
    order: int = 0

    @property
    def bypassed(self) -> bool:
        return self.mode == 4

    @property
    def muted(self) -> bool:
        return self.mode == 2

    @property
    def disabled(self) -> bool:
        return self.mode in (2, 4)

    def links(self) -> Iterator[tuple[str, str, int]]:
        """Every linked input as (input name, source node id, source slot)."""
        for name, value in self.inputs.items():
            if is_link(value):
                yield name, str(value[0]), int(value[1])


def is_link(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


@dataclass(slots=True)
class Graph:
    """A whole workflow, flat, with subgraph boundaries already dissolved."""

    nodes: dict[str, Node] = field(default_factory=dict)

    def __contains__(self, node_id: object) -> bool:
        return str(node_id) in self.nodes

    def __len__(self) -> int:
        return len(self.nodes)

    def __iter__(self) -> Iterator[Node]:
        return iter(sorted(self.nodes.values(), key=lambda node: node.order))

    def get(self, node_id: str | int) -> Node | None:
        return self.nodes.get(str(node_id))

    def add(self, node: Node) -> Node:
        current = self.nodes.get(node.id)
        node.order = node.order or (current.order if current else len(self.nodes) + 1)
        self.nodes[node.id] = node
        return node

    def remove(self, node_id: str | int) -> None:
        self.nodes.pop(str(node_id), None)

    def by_class(self, *class_types: str) -> list[Node]:
        wanted = set(class_types)
        return [node for node in self if node.class_type in wanted]

    def consumers(self, node_id: str | int) -> list[tuple[Node, str, int]]:
        """Every (node, input name, source slot) that reads from *node_id*."""
        key = str(node_id)
        found: list[tuple[Node, str, int]] = []
        for node in self:
            for name, source, slot in node.links():
                if source == key:
                    found.append((node, name, slot))
        return found

    def prompt(self) -> Prompt:
        prompt: Prompt = {}
        for node in self:
            spec = {"class_type": node.class_type, "inputs": dict(node.inputs)}
            if node.title:
                spec["_meta"] = {"title": node.title}
            prompt[node.id] = spec
        return prompt


# --- widget names ----------------------------------------------------------


def declared_widget_names(node: dict[str, Any]) -> list[str]:
    """Widget names in the order the node itself declares them.

    Newer editor exports mark every widget as an input slot, so a node saved today carries
    its own widget order even for classes our static table has never heard of.
    """
    names: list[str] = []
    for slot in node.get("inputs") or []:
        if slot.get("widget") and slot.get("name"):
            names.append(str(slot["name"]))
    return names


def static_widget_names(class_type: str, node: dict[str, Any]) -> Sequence[str] | None:
    """Offline widget order: what the node declares, then our snapshot.

    The node wins because it was written by the editor that saved this file. It is the only
    source that knows how a dynamic combo expanded — `RTXVideoSuperResolution` writes
    `resize_type.scale` or `resize_type.width`/`.height` depending on the mode chosen, and
    no schema can predict which.
    """
    declared = declared_widget_names(node)
    if declared:
        return declared
    return N.WIDGET_ORDER.get(class_type)


# --- links -----------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _Link:
    origin_id: int
    origin_slot: int
    target_id: int
    target_slot: int


def _read_links(raw: Any) -> dict[int, _Link]:
    """Both link shapes: the classic array and the object the new format writes."""
    links: dict[int, _Link] = {}
    if not raw:
        return links
    items: Iterable[Any] = raw.values() if isinstance(raw, dict) else raw
    for item in items:
        try:
            if isinstance(item, dict):
                link_id = int(item["id"])
                link = _Link(
                    int(item["origin_id"]),
                    int(item.get("origin_slot") or 0),
                    int(item["target_id"]),
                    int(item.get("target_slot") or 0),
                )
            else:
                link_id = int(item[0])
                link = _Link(int(item[1]), int(item[2] or 0), int(item[3]), int(item[4] or 0))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        links[link_id] = link
    return links


# --- reading ---------------------------------------------------------------


class _Level:
    """One graph level: the top-level workflow, or the body of one subgraph instance."""

    def __init__(
        self,
        *,
        nodes: list[dict[str, Any]],
        links: Any,
        path: tuple[int, ...],
        subgraphs: dict[str, dict[str, Any]],
        boundary: dict[int, Any],
        graph: Graph,
        widget_names: WidgetNames,
        inherited_mode: int = 0,
    ) -> None:
        self.by_local: dict[int, dict[str, Any]] = {}
        for node in nodes:
            try:
                self.by_local[int(node["id"])] = node
            except (KeyError, TypeError, ValueError):
                continue
        self.links = _read_links(links)
        self.path = path
        self.subgraphs = subgraphs
        self.boundary = boundary
        self.graph = graph
        self.widget_names = widget_names
        self.inherited_mode = inherited_mode
        self.input_node_id: int | None = None
        self._instances: dict[int, dict[int, Any]] = {}
        self._resolving: set[int] = set()

    # -- ids

    def flat(self, local_id: int) -> str:
        return ":".join(str(part) for part in (*self.path, local_id))

    # -- resolution

    def _from_boundary(self, node_id: int) -> bool:
        """Is *node_id* the subgraph's input side rather than a node?

        The editor writes a sentinel (`-10`) for the input side and also records it as
        `inputNode.id`. The two have disagreed across versions, so a negative id that is not a
        node at this level is taken at its word.
        """
        if self.input_node_id is not None and node_id == self.input_node_id:
            return True
        return node_id < 0 and node_id not in self.by_local

    def _origin_value(self, origin_id: int, origin_slot: int) -> Any:
        """What an output slot at this level actually is, once boundaries are dissolved."""
        if self._from_boundary(origin_id):
            return self.boundary.get(origin_slot)

        node = self.by_local.get(origin_id)
        if node is None:
            return None
        class_type = _class_of(node)

        if class_type in self.subgraphs:
            outputs = self._instance_outputs(origin_id)
            return outputs.get(origin_slot)

        if class_type in _PASS_THROUGH_TYPES:
            if origin_id in self._resolving:
                return None
            self._resolving.add(origin_id)
            try:
                for slot in node.get("inputs") or []:
                    value = self._slot_value(slot)
                    if value is not _MISSING:
                        return value
            finally:
                self._resolving.discard(origin_id)
            return None

        if class_type in N.UI_ONLY_TYPES or not class_type:
            return None

        return [self.flat(origin_id), int(origin_slot)]

    def _slot_value(self, slot: dict[str, Any]) -> Any:
        link_id = slot.get("link")
        if link_id is None:
            return _MISSING
        link = self.links.get(int(link_id))
        if link is None:
            return _MISSING
        return self._origin_value(link.origin_id, link.origin_slot)

    # -- subgraph instances

    def _instance_outputs(self, local_id: int) -> dict[int, Any]:
        cached = self._instances.get(local_id)
        if cached is not None:
            return cached
        self._instances[local_id] = {}  # cycle guard
        node = self.by_local[local_id]
        definition = self.subgraphs[_class_of(node)]
        outputs = self._enter(local_id, node, definition)
        self._instances[local_id] = outputs
        return outputs

    def _enter(
        self, local_id: int, node: dict[str, Any], definition: dict[str, Any]
    ) -> dict[int, Any]:
        boundary = self._boundary_of(node, definition)
        mode = _mode_of(node) or self.inherited_mode
        inner = _Level(
            nodes=definition.get("nodes") or [],
            links=definition.get("links"),
            path=(*self.path, local_id),
            subgraphs=self.subgraphs,
            boundary=boundary,
            graph=self.graph,
            widget_names=self.widget_names,
            inherited_mode=mode,
        )
        inner.input_node_id = _boundary_node_id(definition, "inputNode")
        return inner.run(output_node_id=_boundary_node_id(definition, "outputNode"))

    def _boundary_of(
        self, node: dict[str, Any], definition: dict[str, Any]
    ) -> dict[int, Any]:
        """What the instance hands each of the subgraph's input slots.

        A promoted widget arrives as a value in the instance's own `widgets_values`; a wired
        input arrives as a link to resolve at this level.
        """
        boundary: dict[int, Any] = {}
        slots = node.get("inputs") or []
        values = node.get("widgets_values")
        widget_index = 0
        for index, slot in enumerate(slots):
            value = self._slot_value(slot)
            if value is not _MISSING:
                boundary[index] = value
            if slot.get("widget"):
                if isinstance(values, (list, tuple)) and widget_index < len(values):
                    if index not in boundary:
                        boundary[index] = values[widget_index]
                widget_index += 1
        # Older exports keep promoted widget values positionally against the definition's
        # input list rather than against the instance's slots.
        if not slots and isinstance(values, (list, tuple)):
            for index, value in enumerate(values):
                if index < len(definition.get("inputs") or []):
                    boundary[index] = value
        return boundary

    # -- the level itself

    def run(self, *, output_node_id: int | None = None) -> dict[int, Any]:
        instances: list[int] = []
        for local_id, node in self.by_local.items():
            class_type = _class_of(node)
            if not class_type:
                continue
            if class_type in self.subgraphs:
                self._instance_outputs(local_id)
                instances.append(local_id)
                continue
            if class_type in N.UI_ONLY_TYPES or class_type in _PASS_THROUGH_TYPES:
                continue
            self.graph.add(self._node(local_id, node, class_type))

        # A sibling instance may consume one output slot while providing another. Resolving
        # whole instances recursively makes that acyclic slot flow look cyclic on the first
        # pass. Re-evaluate each instance after its siblings have published provisional
        # outputs, once per possible dependency hop.
        for _ in instances:
            for local_id in instances:
                node = self.by_local[local_id]
                definition = self.subgraphs[_class_of(node)]
                self._instances[local_id] = self._enter(local_id, node, definition)

        # Inputs on ordinary nodes may have observed provisional instance outputs.
        for local_id, node in self.by_local.items():
            class_type = _class_of(node)
            if (
                not class_type
                or class_type in self.subgraphs
                or class_type in N.UI_ONLY_TYPES
                or class_type in _PASS_THROUGH_TYPES
            ):
                continue
            self.graph.add(self._node(local_id, node, class_type))

        outputs: dict[int, Any] = {}
        for link in self.links.values():
            if not self._to_boundary(link.target_id, output_node_id):
                continue
            outputs[link.target_slot] = self._origin_value(link.origin_id, link.origin_slot)
        return outputs

    def _to_boundary(self, node_id: int, output_node_id: int | None) -> bool:
        """Does this link leave the subgraph? Same sentinel story as `_from_boundary`."""
        if output_node_id is not None and node_id == output_node_id:
            return True
        if node_id >= 0 or node_id in self.by_local:
            return False
        return not self._from_boundary(node_id)

    def _node(self, local_id: int, node: dict[str, Any], class_type: str) -> Node:
        inputs: dict[str, Any] = {}
        input_types: dict[str, str] = {}
        for slot in node.get("inputs") or []:
            name = slot.get("name")
            if not name:
                continue
            if slot.get("type"):
                input_types[str(name)] = str(slot["type"])
            value = self._slot_value(slot)
            if value is _MISSING or value is None:
                continue
            inputs[str(name)] = value

        _fold_widgets(class_type, node, inputs, self.widget_names)

        mode = _mode_of(node) or self.inherited_mode
        return Node(
            id=self.flat(local_id),
            class_type=class_type,
            inputs=inputs,
            title=str(node.get("title") or ""),
            mode=mode,
            input_types=input_types,
            output_types=tuple(
                str(slot.get("type") or "") for slot in node.get("outputs") or []
            ),
            path=self.path,
            local_id=local_id,
        )


def _class_of(node: dict[str, Any]) -> str:
    return str(node.get("type") or node.get("class_type") or "")


def _mode_of(node: dict[str, Any]) -> int:
    try:
        return int(node.get("mode") or 0)
    except (TypeError, ValueError):
        return 0


def _boundary_node_id(definition: dict[str, Any], key: str) -> int | None:
    boundary = definition.get(key)
    if isinstance(boundary, dict) and boundary.get("id") is not None:
        try:
            return int(boundary["id"])
        except (TypeError, ValueError):
            return None
    return None


def _fold_widgets(
    class_type: str,
    node: dict[str, Any],
    inputs: dict[str, Any],
    widget_names: WidgetNames,
) -> None:
    """Fold positional widget values into named inputs. A link always wins."""
    named = node.get("widgets_values_named")
    if isinstance(named, dict):
        for key, value in named.items():
            if key not in {"videopreview", "h3s_ui", "control_after_generate"} and key not in inputs:
                inputs[key] = value
        return

    values = node.get("widgets_values")
    if values is None:
        return

    if isinstance(values, dict):
        for key, value in values.items():
            if key != "videopreview" and key not in inputs:
                inputs[key] = value
        return

    names = widget_names(class_type, node) or ()
    if not names:
        return

    if not isinstance(values, (list, tuple)):
        if len(names) == 1 and names[0] not in inputs:
            inputs[names[0]] = values
        return

    for index, name in enumerate(names):
        if index >= len(values):
            break
        if name in inputs:
            continue
        value = values[index]
        # A null widget means "leave the node's own default alone", except for lora_mode
        # where null is the meaningful "no LoRA" value.
        if value is None and name != "lora_mode":
            continue
        inputs[name] = value


def read(workflow: dict[str, Any], *, widget_names: WidgetNames | None = None) -> Graph:
    """Flatten a saved workflow into executable nodes."""
    definitions = workflow.get("definitions") or {}
    subgraphs = {
        str(definition.get("id")): definition
        for definition in definitions.get("subgraphs") or []
        if definition.get("id")
    }
    graph = Graph()
    level = _Level(
        nodes=list(workflow.get("nodes") or []),
        links=workflow.get("links"),
        path=(),
        subgraphs=subgraphs,
        boundary={},
        graph=graph,
        widget_names=widget_names or static_widget_names,
    )
    level.run()
    return graph


def _passthrough_source(node: Node, slot: int) -> tuple[str, int] | None:
    wanted = node.output_types[slot] if slot < len(node.output_types) else ""
    links = list(node.links())
    if wanted:
        for name, source, source_slot in links:
            if node.input_types.get(name) == wanted:
                return source, source_slot
    if len(links) == 1:
        _name, source, source_slot = links[0]
        return source, source_slot
    return None


def _drop_disabled(graph: Graph, node: Node) -> None:
    for consumer, name, slot in graph.consumers(node.id):
        replacement = _passthrough_source(node, slot) if node.bypassed else None
        if replacement is None:
            consumer.inputs.pop(name, None)
        else:
            consumer.inputs[name] = [replacement[0], replacement[1]]
    graph.remove(node.id)


def executable(
    workflow: dict[str, Any], *, widget_names: WidgetNames | None = None
) -> tuple[Prompt, Graph]:
    """Flatten an editor workflow and apply ordinary muted/bypassed node modes."""
    graph = read(workflow, widget_names=widget_names)
    for node in list(graph):
        if node.disabled:
            _drop_disabled(graph, node)
    return graph.prompt(), graph


def to_api_prompt(
    workflow: dict[str, Any], *, widget_names: WidgetNames | None = None
) -> Prompt:
    """Flatten an editor workflow into the API prompt shape."""
    return read(workflow, widget_names=widget_names).prompt()


def _definitions(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(definition.get("id")): definition
        for definition in (workflow.get("definitions") or {}).get("subgraphs") or []
        if definition.get("id")
    }


def source_nodes(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The saved node behind every flat id, subgraph instances dissolved.

    `read` throws the drawing away; the export needs it back. Same walk, same ids, so a node
    the prompt names can be drawn where its template drew it.
    """
    subgraphs = _definitions(workflow)
    found: dict[str, dict[str, Any]] = {}

    def walk(nodes: list[dict[str, Any]], path: tuple[int, ...], entered: frozenset[str]) -> None:
        for node in nodes:
            try:
                local = int(node["id"])
            except (KeyError, TypeError, ValueError):
                continue
            class_type = _class_of(node)
            definition = subgraphs.get(class_type)
            if definition is not None:
                if class_type in entered:  # a definition holding itself would not terminate
                    continue
                walk(
                    definition.get("nodes") or [],
                    (*path, local),
                    entered | {class_type},
                )
                continue
            found[":".join(str(part) for part in (*path, local))] = node

    walk(list(workflow.get("nodes") or []), (), frozenset())
    return found


def source_groups(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Every group box, the outer ones and the ones drawn inside a subgraph."""
    subgraphs = _definitions(workflow)
    groups = list(workflow.get("groups") or [])

    def walk(level: dict[str, Any], entered: frozenset[str]) -> None:
        for node in level.get("nodes") or []:
            class_type = _class_of(node)
            definition = subgraphs.get(class_type)
            if definition is None or class_type in entered:
                continue
            groups.extend(definition.get("groups") or [])
            walk(definition, entered | {class_type})

    walk(workflow, frozenset())
    return groups


def load_workflow(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

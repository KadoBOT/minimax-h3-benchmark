"""Projecting an executable prompt back into the editor's node/link notation.

An API prompt is the graph with the drawing thrown away. ComfyUI can still load one — it
reconstructs bare boxes from `{id: {class_type, inputs}}` — but the result has no layout, no
groups, no notes, and none of the widget arrangement a human built. That is what the lab was
shipping in both places a workflow leaves it: the download and the PNG saved beside the video.

So this module projects the prompt back. The template supplies everything the prompt dropped
on the way out — position, size, colour, group, note — and the prompt supplies the graph.

The export is flat: a template that folds its pipeline into a subgraph is dissolved, because
the prompt is what ran and what ran has no subgraphs in it. The nodes keep the coordinates
they were drawn at inside the subgraph, and its group boxes come up with them, so the export
reads like the template with the box opened. Ids cannot survive that — `169:23` is not a
number — so a dissolved node is given a fresh id and `extra.h3lab.node_ids` records which,
letting a ComfyUI log line about `169:23` still be found in the file.

The projection is deliberately one-directional and lossy in only one sense: a node the run
does not use is not in the export at all, because that is the honest description of what ran.

`apply_config` stays the only thing that decides what a run's graph is. Writing the wiring
rules a second time here, in the other notation, is exactly the drift this avoids.
"""

from __future__ import annotations

import copy
from typing import Any

from h3lab.comfy import nodes as N
from h3lab.comfy.graph import Prompt
from h3lab.comfy.workflow import (
    is_link,
    source_groups,
    source_nodes,
    static_widget_names,
    to_api_prompt as read_api_prompt,
)
from h3lab.domain.run import Run

Workflow = dict[str, Any]

_DEFAULT_SIZE = (300, 100)
_SYNTHESISED_POS_ORIGIN = (-5600, -2200)
_SYNTHESISED_POS_STRIDE = 120


def run_provenance(run: Run) -> dict[str, Any]:
    """What an exported workflow should say about the run it came from.

    The graph already carries every setting, so this is only the run's identity — enough to
    find the row again from a file somebody kept, or from a PNG they were sent.
    """
    return {
        "run_id": run.id,
        "seq": run.seq,
        "label": run.label,
        "config_hash": run.config_hash,
        "recipe_hash": run.recipe_hash,
    }


def _is_link(value: Any) -> bool:
    """An API prompt spells a connection `[source_id, slot_index]`."""
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    )


class _Ids:
    """Editor ids for prompt ids, keeping the numbers a flat template already used."""

    def __init__(self, workflow: Workflow, template: dict[str, dict[str, Any]]) -> None:
        used = {int(node["id"]) for node in template.values() if _numeric(node.get("id"))}
        try:
            used.add(int(workflow.get("last_node_id") or 0))
        except (TypeError, ValueError):
            pass
        self._next = max(used, default=0) + 1
        self._taken = used
        self.assigned: dict[str, int] = {}
        self.renamed: dict[str, int] = {}

    def of(self, prompt_id: str) -> int:
        known = self.assigned.get(prompt_id)
        if known is not None:
            return known
        if prompt_id.isdigit() and int(prompt_id) in self._taken:
            editor_id = int(prompt_id)
        else:
            editor_id = self._next
            self._next += 1
            self._taken.add(editor_id)
            self.renamed[prompt_id] = editor_id
        self.assigned[prompt_id] = editor_id
        return editor_id


def _numeric(value: Any) -> bool:
    return isinstance(value, int) or (isinstance(value, str) and value.isdigit())


def _synthesised(node_id: int, class_type: str, ordinal: int) -> dict[str, Any]:
    """A node the template does not hold, drawn somewhere it cannot cover anything else.

    `apply_config` mints reference loaders when the template has fewer than the run needs, so
    an r2v export can contain nodes that never had a position. They are laid out in a column
    off to one side rather than at the origin, where they would land on top of the graph.
    """
    outputs = [
        {"localized_name": name, "name": name, "type": kind, "links": []}
        for name, kind in N.OUTPUT_SLOTS.get(class_type, ())
    ]
    return {
        "id": node_id,
        "type": class_type,
        "pos": [
            _SYNTHESISED_POS_ORIGIN[0],
            _SYNTHESISED_POS_ORIGIN[1] + ordinal * _SYNTHESISED_POS_STRIDE,
        ],
        "size": list(_DEFAULT_SIZE),
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": outputs,
        "properties": {"Node name for S&R": class_type},
        "widgets_values": [],
    }


def _reset_slots(node: dict[str, Any]) -> None:
    """Forget the template's wiring. Every surviving connection is re-minted from the prompt."""
    for slot in node.get("inputs") or []:
        slot["link"] = None
    for slot in node.get("outputs") or []:
        slot["links"] = []
    # The video node's preview points at whatever the template's author last rendered. It is
    # playback state, not configuration, and in an export it is a link to somebody else's file.
    values = node.get("widgets_values")
    if isinstance(values, dict):
        values.pop("videopreview", None)


def _output_slot(node: dict[str, Any], index: int) -> dict[str, Any]:
    """The slot the prompt's `[source, index]` refers to, invented if the node lacks it.

    A synthesised loader knows its outputs from `OUTPUT_SLOTS`; anything else the graph mints
    in future would otherwise crash the export rather than lose a name nobody reads.
    """
    slots = node.setdefault("outputs", [])
    while len(slots) <= index:
        position = len(slots)
        slots.append(
            {
                "localized_name": f"output_{position}",
                "name": f"output_{position}",
                "type": "*",
                "links": [],
            }
        )
    return slots[index]


def _input_slot(node: dict[str, Any], name: str, kind: str) -> dict[str, Any]:
    for slot in node.get("inputs") or []:
        if slot.get("name") == name:
            return slot
    # An autogrow input (`ref_images.ref_image_0`) only exists once something is plugged in,
    # so the template has no slot to reuse.
    slot = {"localized_name": name, "name": name, "type": kind, "link": None}
    node.setdefault("inputs", []).append(slot)
    return slot


def _write_widget(node: dict[str, Any], name: str, value: Any) -> None:
    """Put *value* where the reader will read it back as this input.

    A dict-shaped `widgets_values` is keyed; a list-shaped one is positional, and the position
    is the order the node itself declares, falling back to the class table — the same order the
    reader folds by, because anything else would export a value into a different widget.
    """
    values = node.get("widgets_values")

    if isinstance(values, dict):
        values[name] = value
        return

    order = static_widget_names(str(node.get("type") or ""), node) or ()
    if name not in order:
        return
    index = list(order).index(name)
    if not isinstance(values, list):
        values = [] if values is None else [values]
        node["widgets_values"] = values
    while len(values) <= index:
        values.append(None)
    values[index] = value


def to_editor_workflow(
    workflow: Workflow,
    prompt: Prompt,
    *,
    provenance: dict[str, Any] | None = None,
) -> Workflow:
    """The editor workflow that loads as *prompt*, drawn the way *workflow* draws it.

    Reading the export back yields the graph `apply_config` produced — same classes, same
    widget values, same wiring — under the ids in `extra.h3lab.node_ids`. That equality is the
    whole contract: it is what makes the exported file, the graph inside the saved PNG, and the
    run itself the same graph rather than three descriptions of one.
    """
    template = source_nodes(workflow)
    ids = _Ids(workflow, template)

    exported: Workflow = {
        key: copy.deepcopy(value)
        for key, value in workflow.items()
        if key not in ("nodes", "links", "groups", "definitions")
    }

    nodes: list[dict[str, Any]] = []
    by_prompt_id: dict[str, dict[str, Any]] = {}

    # Template order first, so the export reads down the page the way the template does.
    for flat_id, source in template.items():
        node = copy.deepcopy(source)
        spec = prompt.get(flat_id)
        if spec is not None:
            node["id"] = ids.of(flat_id)
            node["type"] = spec.get("class_type") or node.get("type")
            # A node in the prompt is a node that ran; the template may have it bypassed.
            node["mode"] = 0
            _reset_slots(node)
            nodes.append(node)
            by_prompt_id[flat_id] = node
        elif node.get("type") in N.UI_KEPT_TYPES:
            node["id"] = ids.of(flat_id)
            nodes.append(node)

    synthesised = 0
    for flat_id, spec in prompt.items():
        if flat_id in by_prompt_id:
            continue
        node = _synthesised(ids.of(flat_id), str(spec.get("class_type") or ""), synthesised)
        nodes.append(node)
        by_prompt_id[flat_id] = node
        synthesised += 1

    links: list[list[Any]] = []
    next_link = 1

    for flat_id, spec in prompt.items():
        node = by_prompt_id[flat_id]
        for name, value in (spec.get("inputs") or {}).items():
            if not _is_link(value):
                _write_widget(node, name, value)
                continue
            source_node = by_prompt_id.get(str(value[0]))
            if source_node is None:
                continue
            slot_index = int(value[1])
            slot = _output_slot(source_node, slot_index)
            kind = str(slot.get("type") or "*")
            links.append(
                [next_link, int(source_node["id"]), slot_index, int(node["id"]), 0, kind]
            )
            slot.setdefault("links", []).append(next_link)
            _input_slot(node, name, kind)["link"] = next_link
            next_link += 1

    # An input's index is its position among the node's slots, which is only final once every
    # slot exists — so the links carry a placeholder until here.
    by_editor_id = {int(node["id"]): node for node in nodes}
    for edge in links:
        target = by_editor_id[int(edge[3])]
        edge[4] = next(
            index
            for index, slot in enumerate(target.get("inputs") or [])
            if slot.get("link") == edge[0]
        )

    exported["nodes"] = nodes
    exported["links"] = links
    exported["groups"] = copy.deepcopy(source_groups(workflow))
    exported["last_node_id"] = max(by_editor_id, default=0)
    exported["last_link_id"] = next_link - 1

    extra = exported.setdefault("extra", {})
    stamp: dict[str, Any] = dict(provenance or {})
    if ids.renamed:
        stamp["node_ids"] = dict(ids.renamed)
    if stamp:
        extra["h3lab"] = stamp

    return exported


def exported_ids(exported: Workflow) -> dict[str, int]:
    """The prompt id → editor id map an export was written under."""
    stamp = (exported.get("extra") or {}).get("h3lab") or {}
    return {str(key): int(value) for key, value in (stamp.get("node_ids") or {}).items()}


def prompt_of(exported: Workflow) -> Prompt:
    """Read an export back as the prompt it was projected from.

    The inverse of `to_editor_workflow`, undoing the renumbering a dissolved subgraph forces,
    so an export can be compared with the run it claims to describe.
    """
    original = {str(value): key for key, value in exported_ids(exported).items()}
    out: Prompt = {}
    for node_id, spec in read_api_prompt(exported).items():
        inputs = {
            name: (
                [original.get(str(value[0]), str(value[0])), int(value[1])]
                if is_link(value)
                else value
            )
            for name, value in spec["inputs"].items()
        }
        out[original.get(node_id, node_id)] = {
            "class_type": spec["class_type"],
            "inputs": inputs,
        }
    return out

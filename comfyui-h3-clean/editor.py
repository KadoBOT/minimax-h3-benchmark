"""Read the flat, editable ComfyUI graph used by the H3 API."""


WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
UI_TYPES = {"Note", "MarkdownNote", "PrimitiveNode", "Reroute"}


def widget_values(schema, values):
    values = iter(values)
    result = {}

    def read(inputs, prefix=""):
        for section in ("required", "optional"):
            for name, spec in inputs.get(section, {}).items():
                kind = spec[0]
                options = spec[1] if len(spec) > 1 else {}
                if options.get("forceInput"):
                    continue
                key = prefix + name
                if kind == "COMFY_DYNAMICCOMBO_V3":
                    value = next(values)
                    result[key] = value
                    choice = next(item for item in options["options"] if item["key"] == value)
                    read(choice["inputs"], key + ".")
                elif isinstance(kind, list) or kind in WIDGET_TYPES:
                    result[key] = next(values)
                    if options.get("control_after_generate"):
                        next(values)

    read(schema["input"])
    return result


def to_prompt(workflow, node_info):
    if workflow.get("definitions", {}).get("subgraphs"):
        raise ValueError("Expand subgraphs before saving an H3 API preset")
    nodes = {str(node["id"]): node for node in workflow["nodes"]}
    links = {}
    for link in workflow.get("links", []):
        if isinstance(link, dict):
            links[link["id"]] = (str(link["origin_id"]), link["origin_slot"])
        else:
            links[link[0]] = (str(link[1]), link[2])

    def source(link_id, seen=()):
        if link_id in seen:
            raise ValueError("Cycle in workflow bypass/reroute links")
        node_id, index = links[link_id]
        node = nodes[node_id]
        if node.get("mode") == 2:
            return None
        if node["type"] == "PrimitiveNode":
            return node["widgets_values"][0]
        if node["type"] == "Reroute":
            return source(node["inputs"][0]["link"], (*seen, link_id))
        if node.get("mode") == 4:
            output_type = node["outputs"][index]["type"]
            compatible = [slot for slot in node.get("inputs", [])
                          if slot.get("link") is not None and slot["type"] in (output_type, "*")]
            if not compatible:
                return None
            return source(compatible[0]["link"], (*seen, link_id))
        return [node_id, index]

    prompt = {}
    for node_id, node in nodes.items():
        if node["type"] in UI_TYPES or node.get("mode") in (2, 4):
            continue
        schema = node_info(node["type"])
        try:
            inputs = widget_values(schema, node.get("widgets_values", []))
        except (StopIteration, KeyError) as error:
            raise ValueError(f"Re-save node {node_id} ({node['type']}) in ComfyUI: its widgets do not match the installed node") from error
        for slot in node.get("inputs", []):
            if slot.get("link") is not None:
                value = source(slot["link"])
                if value is not None:
                    inputs[slot["name"]] = value
        properties = node.get("properties", {})
        meta = {"title": node.get("title") or node["type"]}
        if "h3_role" in properties:
            meta["h3_role"] = properties["h3_role"]
        prompt[node_id] = {"class_type": node["type"], "inputs": inputs, "_meta": meta}
    return prompt

"""
Utilities for formatting SWE-bench Pro `interface` and `requirements` fields
into a structured markdown hints string for use with mini-SWE-agent.

Output format:

    ## Requirements
    - ...

    ## Entity 1: `Name`
    - **Kind:** Function
    - **Path:** `path/to/file.py`
    - **Description:** ...

    **Signature:**
    ```python
    def name(input) -> output
    ```

    ## Entity 2: `Name`
    ...

Copy this file to /PATH/TO/SWE-bench_Pro-os/helper_code/create_hints.py
and import create_hints() in generate_minisweagent_instances.py.
"""

import re


NO_HINTS_MARKER = "No new interfaces are introduced"


# ---------------------------------------------------------------------------
# Interface parser
# ---------------------------------------------------------------------------

# Keys we recognise in interface blocks (case-insensitive, various spellings)
_KEY_ALIASES = {
    "type": "type",
    "name": "name",
    "path": "path",
    "pathfile": "path",
    "location": "path",
    "locations": "path",
    "input": "input",
    "inputs": "input",
    "output": "output",
    "outputs": "output",
    "description": "description",
    "public api": "public_api",
    "public_api": "public_api",
    "inherits from": "input",
}

_KEY_RE = re.compile(
    r"^\s*[-*]?\s*(" + "|".join(re.escape(k) for k in _KEY_ALIASES) + r")\s*:\s*(.*)$",
    re.IGNORECASE,
)


def _strip_backticks(s: str) -> str:
    return s.strip().strip("`").strip('"').strip("'")


def _parse_interface_blocks(interface: str) -> list[dict]:
    """
    Split the interface string into individual entity blocks and parse
    each one into a dict of normalised keys.
    """
    if not interface or NO_HINTS_MARKER in interface:
        return []

    raw_blocks = re.split(r"\n\s*\n", interface.strip())

    entities = []
    current: dict[str, list[str]] = {}

    def flush():
        if current:
            entities.append({k: " ".join(v).strip() for k, v in current.items()})
        current.clear()

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.splitlines()
        block_parsed: dict[str, list[str]] = {}
        last_key = None

        for line in lines:
            if re.match(r"^(the golden patch introduces|note|also)\b", line.strip(), re.IGNORECASE):
                continue

            m = _KEY_RE.match(line)
            if m:
                raw_key = m.group(1).lower()
                key = _KEY_ALIASES.get(raw_key, raw_key)
                value = m.group(2).strip()
                if key not in block_parsed:
                    block_parsed[key] = []
                block_parsed[key].append(value)
                last_key = key
            elif last_key and line.strip().startswith(("*", "-", " ")):
                block_parsed[last_key].append(line.strip().lstrip("*- "))
            elif block_parsed and last_key:
                block_parsed[last_key].append(line.strip())

        if "name" in block_parsed or "type" in block_parsed:
            flush()
            current = block_parsed
        elif block_parsed and current:
            for k, v in block_parsed.items():
                current.setdefault(k, []).extend(v)
        elif block_parsed:
            current = block_parsed

    flush()
    return entities


# Field order for entity bullet points
_ENTITY_FIELD_ORDER = ["type", "name", "path", "input", "output", "public_api", "description"]

_FIELD_LABELS = {
    "type": "Type",
    "name": "Name",
    "path": "Path",
    "input": "Input",
    "output": "Output",
    "public_api": "Public API",
    "description": "Description",
}


def _format_entity(index: int, entity: dict) -> str:
    lines = [f"## Entity {index}:", ""]
    for key in _ENTITY_FIELD_ORDER:
        value = entity.get(key, "").strip()
        if value:
            label = _FIELD_LABELS[key]
            lines.append(f"- **{label}:** {value}")
    return "\n".join(lines)


def format_interface(interface: str) -> str:
    """Convert raw interface string to markdown entity sections."""
    entities = _parse_interface_blocks(interface)
    if not entities:
        return ""
    return "\n\n".join(_format_entity(i + 1, e) for i, e in enumerate(entities))


# ---------------------------------------------------------------------------
# Requirements formatter
# ---------------------------------------------------------------------------

def format_requirements(requirements: str) -> str:
    """Convert raw requirements string to a markdown ## Requirements section."""
    if not requirements or not requirements.strip():
        return ""

    # Some dataset entries are double-encoded JSON strings (e.g. "\"- item\\n- item\"").
    # Unwrap one level of JSON encoding if the value starts and ends with a quote.
    text = requirements.strip()
    if text.startswith('"') and text.endswith('"'):
        try:
            import json as _json
            text = _json.loads(text)
        except Exception:
            pass

    lines = text.strip().splitlines()
    out = ["## Requirements", ""]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("-", "*", "•")):
            out.append(f"- {stripped.lstrip('-*• ').strip()}")
        else:
            out.append(f"- {stripped}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_hints(row: dict) -> str:
    """
    Build a markdown hints string from a SWE-bench Pro dataset row.

    Combines `requirements` and `interface` fields into structured markdown.
    Returns an empty string if neither field has usable content.
    """
    iface_md = format_interface(row.get("interface", ""))
    req_md = format_requirements(row.get("requirements", ""))
    parts = [p for p in (iface_md, req_md) if p]
    return "\n\n".join(parts)

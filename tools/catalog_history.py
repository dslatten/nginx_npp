"""Keep recognized directive names when an upstream catalog removes them."""

import json
from pathlib import Path


def _names(catalog, field, required=False):
    if not isinstance(catalog, dict):
        raise ValueError("catalog must be a JSON object")
    if required and field not in catalog:
        raise ValueError("catalog is missing " + field)
    names = catalog.get(field, [])
    if not isinstance(names, list) or any(
        not isinstance(name, str) or not name
        or any(character.isspace() or ord(character) < 32 or ord(character) == 127
               for character in name)
        for name in names
    ):
        raise ValueError(field + " must be a list of nonempty single-token names")
    if names != sorted(set(names)):
        raise ValueError(field + " must be sorted and contain no duplicates")
    return set(names)


def preserve_retired_directives(fresh_catalog, output_path):
    """Return a fresh catalog with missing prior names in retired_directives.

    The current ``directives`` list remains an exact source snapshot. Existing
    output must be valid JSON with sorted, unique current and optional retired
    lists. Errors propagate to the caller so a broken prior file is not replaced.
    No input is mutated, no file is written, and an empty retired list is omitted.
    """
    current = _names(fresh_catalog, "directives", required=True)
    # A caller may already have curated retired names; preserve those too.
    retired = _names(fresh_catalog, "retired_directives") - current
    path = Path(output_path)
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        prior_current = _names(previous, "directives", required=True)
        prior_retired = _names(previous, "retired_directives")
        if prior_current & prior_retired:
            raise ValueError("prior current and retired directive lists overlap")
        retired |= (prior_current | prior_retired) - current
    result = dict(fresh_catalog)
    result.pop("retired_directives", None)
    if retired:
        result["retired_directives"] = sorted(retired)
    return result

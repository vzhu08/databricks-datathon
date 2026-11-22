"""Print small reproducible examples using the tracked Find care fixture only."""

import json
from pathlib import Path

from app import find_care
from app.ranking import search_facilities

from .finding_provenance import project_find_care


def examples():
    fixture = Path(find_care.__file__).with_name("demo_facilities.json")
    rows = json.loads(fixture.read_bytes())["facilities"]
    location = find_care.parse_location("302001")
    result = {}
    for radius in (2, 50):
        response = search_facilities("dialysis", location, facilities=rows, radius_km=radius)
        result[f"demo_{radius}_km"] = project_find_care(response, "dialysis", mode="demo")
        result[f"withheld_shape_{radius}_km"] = project_find_care(
            find_care.withheld(response), "dialysis", mode="warehouse")
    return result


if __name__ == "__main__":
    print(json.dumps(examples(), indent=2, sort_keys=True, allow_nan=False))

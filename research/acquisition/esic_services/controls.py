"""Control-source readers; no branch allocation or clinical inference."""
import re


def historical_rows(table, expected_rows):
    """Read a four-column historical SST table and its explicit bullet scope."""
    result = []
    for cells in table[1:]:
        if len(cells) != 4 or not re.fullmatch(r"\d+\.?", cells[0].strip()):
            raise ValueError("Unrecognised historical table layout")
        serial = int(cells[0].strip().rstrip("."))
        if serial != len(result) + 1:
            raise ValueError("Historical serial gap")
        mode = "unspecified"
        mentions = []
        for line in cells[3].splitlines():
            if re.search(r"in[ -]house services", line, re.I):
                mode = "in_house"
                continue
            if not line.strip():
                continue
            if not line.lstrip().startswith("\uf0d8"):
                raise ValueError("Unrecognised service bullet")
            mentions.append({"text_original": line,
                             "operator": "PPP_partner_unspecified" if "PPP" in line else mode,
                             "temporal_status": "historical",
                             "current_service_decision": "unconfirmed"})
        result.append({"serial": serial, "state_original": cells[1],
                       "name_original": cells[2], "services_original": cells[3],
                       "mentions": mentions})
    if len(result) != expected_rows:
        raise ValueError("Historical table count mismatch")
    return result


def release_paragraphs(document):
    """Read only the official release body, avoiding the duplicated print DOM."""
    from lxml import html
    tree = html.fromstring(document)
    bodies = tree.xpath('//div[@id="pibReleaseBody"]')
    if len(bodies) != 1:
        raise ValueError("Expected one official release body")
    return [{"paragraph_index_zero_based": i,
             "text_original": "".join(node.itertext()),
             "text_whitespace_normalized": " ".join("".join(node.itertext()).split())}
            for i, node in enumerate(bodies[0].xpath('.//p'))]


def quantity_observation(paragraph, excerpt, value, unit, scope):
    """Validate a reviewed count without converting beds into equipment/slots."""
    text = paragraph["text_whitespace_normalized"]
    if excerpt not in text:
        raise ValueError("Count excerpt is not present at its cited paragraph")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("Count must be a nonnegative integer")
    if unit not in {"beds", "operation_theatres", "OT_suites", "patients", "machines"}:
        raise ValueError("Unknown count unit")
    number = re.search(r"\b(?:\d[\d,]*|five)\b", excerpt, re.I)
    if number is None or (5 if number.group().lower() == "five" else int(number.group().replace(",", ""))) != value:
        raise ValueError("Count differs from its excerpt")
    unit_words = {"beds": r"\bbeds?\b", "operation_theatres": r"\boperation theatres\b",
                  "OT_suites": r"\bOT suites\b", "patients": r"\bpatients\b", "machines": r"\bmachines?\b"}
    if not re.search(unit_words[unit], excerpt, re.I):
        raise ValueError("Count unit differs from its excerpt")
    if scope not in {"pooled_twin_hospitals", "explicit_medical_college", "explicit_super_speciality"}:
        raise ValueError("Count requires an explicit source scope")
    return {"paragraph_index_zero_based": paragraph["paragraph_index_zero_based"],
            "excerpt": excerpt, "quantity": value, "unit": unit, "scope": scope,
            "derived_machine_count": None, "derived_staffed_slots": None,
            "allocation_to_other_campuses": None}

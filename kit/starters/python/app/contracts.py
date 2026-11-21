"""Wire validation uses the generated TypeScript schema, never a second schema copy."""
import json
import os
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
from pydantic import RootModel, model_validator

SCHEMA_PATH = Path(os.environ.get("KIT_CONTRACT_SCHEMA", Path(__file__).resolve().parents[3] / "packages/contracts/schema.json"))
SCHEMA = json.loads(SCHEMA_PATH.read_text())

def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2

def validate_contract(name: str, value: Any) -> Any:
    Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]}).validate(value)
    if name == "TransformRequest" and utf16_length(value["text"]) > 100_000:
        raise ValueError("Text exceeds UTF-16 limit")
    if name == "Document":
        size = utf16_length(value["text"])
        ids = set()
        for segment in value["segments"]:
            if segment["id"] in ids or not 0 <= segment["start"] <= segment["end"] <= size:
                raise ValueError("Invalid document segment")
            ids.add(segment["id"])
    return value

class TransformInput(RootModel[dict[str, Any]]):
    @model_validator(mode="after")
    def validate_wire(self):
        try:
            validate_contract("TransformRequest", self.root)
        except Exception as error:
            raise ValueError("Invalid transform request") from error
        return self

class TransformOutput(RootModel[dict[str, Any]]):
    @model_validator(mode="after")
    def validate_wire(self):
        validate_contract("TransformResult", self.root)
        return self

class DocumentOutput(RootModel[dict[str, Any]]):
    @model_validator(mode="after")
    def validate_wire(self):
        validate_contract("Document", self.root)
        return self

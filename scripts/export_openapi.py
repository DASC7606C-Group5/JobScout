"""Write the API schema used to generate the browser client."""

import json
from pathlib import Path

from jobscout.main import create_app

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "web" / ".tools" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

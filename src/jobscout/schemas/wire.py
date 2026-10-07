"""JSON response schemas include every serialized default field."""

from pydantic import BaseModel, ConfigDict


class WireModel(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

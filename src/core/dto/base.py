from pydantic import BaseModel, ConfigDict


class BaseDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class FrozenBaseDTO(BaseDTO):
    model_config = ConfigDict(extra="forbid", from_attributes=True, frozen=True)

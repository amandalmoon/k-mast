from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Weight = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
Amount = Annotated[Decimal, Field(allow_inf_nan=False)]
Nonnegative = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

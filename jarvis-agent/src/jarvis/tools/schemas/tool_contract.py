from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContract:
    tool_name: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]


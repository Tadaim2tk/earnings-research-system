"""Schema metadata models used by the CSV validator."""

from typing import List, Optional

from pydantic import BaseModel, Field


class ColumnSpec(BaseModel):
    """Column-level validation metadata."""

    name: str
    type: str
    required: bool = False
    allowed: Optional[List[str]] = None
    min: Optional[float] = None
    max: Optional[float] = None


class ForeignKeySpec(BaseModel):
    """Cross-table reference metadata."""

    columns: List[str]
    ref_table: str
    ref_columns: List[str]
    nullable: bool = False


class TableSpec(BaseModel):
    """CSV table validation metadata."""

    table: str
    file: str
    primary_key: List[str]
    unique: List[List[str]] = Field(default_factory=list)
    foreign_keys: List[ForeignKeySpec] = Field(default_factory=list)
    columns: List[ColumnSpec]

    @property
    def required_columns(self):
        """Return all declared column names."""
        return [column.name for column in self.columns]

"""Shared, validated request parameters."""
from typing import Annotated

from fastapi import Path, Query
from pydantic import StringConstraints

ActorCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,6}$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=80)]
YearParam = Annotated[int | None, Query(ge=2015, le=2025)]
IncludeSynthetic = Annotated[bool, Query(description="Include rows the source flags as synthetic")]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
PathCode = Annotated[str, Path(pattern=r"^[A-Z]{2,6}$")]


def page(items: list, total: int, limit: int, offset: int) -> dict:
    return {"items": items, "total": total, "limit": limit, "offset": offset}

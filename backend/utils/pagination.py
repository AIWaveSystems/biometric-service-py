from math import ceil
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from ..schemas import PaginationParams


def paginate(
    db: Session,
    query: Select,
    params: PaginationParams,
    search_columns: tuple[Any, ...],
    sort_columns: dict[str, Any],
) -> tuple[list[Any], dict[str, int]]:
    if params.search:
        pattern = f"%{params.search}%"
        query = query.where(or_(*(column.ilike(pattern) for column in search_columns)))

    sort_column = sort_columns.get(params.sort_by)
    if sort_column is None:
        allowed = ", ".join(sort_columns)
        raise ValueError(f"Ordenamiento invalido. Opciones: {allowed}")

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    ordering = sort_column.asc() if params.sort_dir == "asc" else sort_column.desc()
    rows = db.execute(
        query.order_by(ordering).offset((params.page - 1) * params.limit).limit(params.limit)
    ).scalars().all()
    return rows, {
        "page": params.page,
        "limit": params.limit,
        "total": total,
        "pages": ceil(total / params.limit) if total else 0,
    }


def paginated_response(items: list[Any], meta: dict[str, int]) -> dict[str, Any]:
    return {"items": items, **meta}

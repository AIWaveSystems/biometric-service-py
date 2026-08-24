from fastapi import Request
from sqlalchemy import Select


def api_client_id(request: Request) -> int | None:
    return getattr(request.state, "client_id", None)


def scope_user_query(query: Select, request: Request, user_column) -> Select:
    client_id = api_client_id(request)
    if client_id is not None:
        return query.where(user_column.api_client_id == client_id)
    return query

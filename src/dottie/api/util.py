from typing import Any


def build[M](model: type[M], obj: object, **extra: Any) -> M:
    """A response model from a database row plus the fields the row does not have (a count, a related name)."""
    fields = {name: getattr(obj, name) for name in model.model_fields if name not in extra}  # pyright: ignore[reportAttributeAccessIssue]
    return model(**fields, **extra)

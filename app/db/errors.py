from sqlalchemy.exc import IntegrityError

UNIQUE_VIOLATION = "23505"


def is_unique_violation(err: IntegrityError) -> bool:
    return getattr(err.orig, "sqlstate", None) == UNIQUE_VIOLATION

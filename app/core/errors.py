class DomainError(Exception):
    """Base class for expected business errors. The message is shown to the client."""


class NotFoundError(DomainError):
    pass


class ForbiddenError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class UnauthorizedError(DomainError):
    pass

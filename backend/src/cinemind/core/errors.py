"""Typed domain exceptions. The API turns them into `{code, message}` responses."""


class DomainError(Exception):
    """Base error: `code` is machine readable, `message` is plain language for the user."""

    code = "error"
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    code = "not_found"
    status_code = 404


class InvalidInputError(DomainError):
    code = "invalid_input"
    status_code = 422


class PathNotAllowedError(DomainError):
    code = "path_not_allowed"
    status_code = 403


class JobStateError(DomainError):
    code = "job_state"
    status_code = 409


class JobCancelled(Exception):
    """Raised inside a stage when the user cancelled the job."""

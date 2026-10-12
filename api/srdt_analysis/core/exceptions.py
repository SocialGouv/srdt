from typing import Optional


class SRDTException(Exception):
    def __init__(
        self, message: str, status_code: int = 500, service: Optional[str] = None
    ):
        self.status_code = status_code
        self.service = service
        super().__init__(message)


class ConfigurationError(SRDTException):
    """Missing env var or config, not a downstream failure."""


class ExternalServiceError(SRDTException):
    """Downstream service returned an unexpected error."""

    def __init__(
        self, message: str, status_code: int = 502, service: Optional[str] = None
    ):
        super().__init__(message, status_code=status_code, service=service)


class ServiceUnavailableError(ExternalServiceError):
    """Downstream service unreachable or timed out."""

    def __init__(self, message: str, service: Optional[str] = None):
        super().__init__(message, status_code=503, service=service)

from __future__ import annotations


class MVAError(Exception):
    """Base error carrying a stable, user-facing category."""

    code = "mva_error"
    retryable = False

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ConfigurationError(MVAError):
    code = "configuration_error"


class SessionNotFoundError(MVAError):
    code = "session_not_found"


class StorageError(MVAError):
    code = "storage_error"


class ModelError(MVAError):
    code = "model_error"


class ModelAuthenticationError(ModelError):
    code = "model_authentication_error"


class ModelBalanceError(ModelError):
    code = "model_balance_error"


class ModelRateLimitError(ModelError):
    code = "model_rate_limit_error"
    retryable = True


class ModelServiceError(ModelError):
    code = "model_service_error"
    retryable = True


class ModelRequestError(ModelError):
    code = "model_request_error"


class ModelProtocolError(ModelError):
    code = "model_protocol_error"


class ToolRegistrationError(MVAError):
    code = "tool_registration_error"


class ToolValidationError(MVAError):
    code = "tool_validation_error"


"""
Custom exceptions for Third Place Platform
"""


class ThirdPlaceException(Exception):
    """Base exception for all Third Place Platform errors"""
    def __init__(self, message: str, error_code: str = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__


class ValidationError(ThirdPlaceException):
    """Raised when validation fails"""
    pass


class InsuranceValidationError(ThirdPlaceException):
    """Raised when insurance validation fails"""
    pass


class CoverageError(ThirdPlaceException):
    """Raised when there's an issue with insurance coverage"""
    pass


class ClassificationError(ThirdPlaceException):
    """Raised when activity classification fails"""
    pass


class AccessDeniedError(ThirdPlaceException):
    """Raised when access is denied"""
    pass


class NotFoundError(ThirdPlaceException):
    """Raised when a resource is not found"""
    pass


class RepositoryError(ThirdPlaceException):
    """Raised when repository operation fails"""
    pass


class AuthenticationError(ThirdPlaceException):
    """Raised when authentication fails"""
    pass


class AuthorizationError(ThirdPlaceException):
    """Raised when authorization fails"""
    pass


class TokenError(ThirdPlaceException):
    """Raised when there's an issue with JWT token"""
    pass


class CapacityExceededError(ThirdPlaceException):
    """Raised when capacity limit is exceeded"""
    pass


class ConflictError(ThirdPlaceException):
    """Raised when there's a resource conflict"""
    pass


class ExternalServiceError(ThirdPlaceException):
    """Raised when external service call fails"""
    pass


class ConfigurationError(ThirdPlaceException):
    """Raised when configuration is invalid"""
    pass

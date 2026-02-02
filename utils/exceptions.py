class InsuranceValidationError(Exception):
    """Raised when there's an issue with insurance validation"""
    pass


class CoverageError(Exception):
    """Raised when there's an issue with insurance coverage"""
    pass


class ClassificationError(Exception):
    """Raised when there's an issue with activity classification"""
    pass


class AccessDeniedError(Exception):
    """Raised when access is denied"""
    pass


class ValidationError(Exception):
    """General validation error"""
    pass
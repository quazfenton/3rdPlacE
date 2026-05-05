"""
Input Validation and Sanitization Utilities for Third Place Platform

Provides validation and sanitization for:
- Metadata fields (JSONB)
- URLs
- Text input
- File uploads
"""
import re
import json
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse


# =============================================================================
# Constants
# =============================================================================

MAX_METADATA_SIZE = 10240  # 10KB max for metadata
MAX_URL_LENGTH = 2048
MAX_STRING_LENGTH = 5000
MAX_LIST_ITEMS = 100
MAX_DICT_KEYS = 50

# Dangerous HTML/JS patterns to sanitize
DANGEROUS_PATTERNS = [
    (re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL), ''),
    (re.compile(r'javascript:', re.IGNORECASE), ''),
    (re.compile(r'on\w+\s*=', re.IGNORECASE), ''),  # onclick=, onerror=, etc.
    (re.compile(r'<[^>]+>'), ''),  # Strip all HTML tags
]


# =============================================================================
# Metadata Validation
# =============================================================================

class MetadataValidationError(Exception):
    """Raised when metadata validation fails"""
    pass


def validate_metadata(
    data: Any,
    max_size: int = MAX_METADATA_SIZE,
    sanitize: bool = True
) -> Dict[str, Any]:
    """
    Validate and optionally sanitize metadata.
    
    Args:
        data: The metadata to validate
        max_size: Maximum serialized size in bytes
        sanitize: Whether to sanitize dangerous content
        
    Returns:
        Validated and sanitized metadata dict
        
    Raises:
        MetadataValidationError: If validation fails
    """
    if data is None:
        return {}
    
    if not isinstance(data, dict):
        raise MetadataValidationError("Metadata must be a dictionary")
    
    # Check serialized size
    try:
        serialized = json.dumps(data)
        if len(serialized) > max_size:
            raise MetadataValidationError(
                f"Metadata exceeds maximum size ({max_size} bytes). "
                f"Got {len(serialized)} bytes."
            )
    except (TypeError, ValueError) as e:
        raise MetadataValidationError(f"Metadata is not JSON serializable: {e}")
    
    # Sanitize if requested
    if sanitize:
        data = _sanitize_dict(data)
    
    return data


def _sanitize_dict(data: Dict, depth: int = 0, max_depth: int = 10) -> Dict:
    """
    Recursively sanitize dictionary values.
    
    Args:
        data: Dictionary to sanitize
        depth: Current recursion depth
        max_depth: Maximum recursion depth
        
    Returns:
        Sanitized dictionary
    """
    if depth > max_depth:
        return {"_error": "Maximum nesting depth exceeded"}
    
    result = {}
    key_count = 0
    
    for key, value in data.items():
        if key_count >= MAX_DICT_KEYS:
            break
        
        # Sanitize key
        if not isinstance(key, str):
            key = str(key)
        key = _sanitize_string(key[:100])  # Limit key length
        key = re.sub(r'[_\-\s]+', '_', key.lower())  # Normalize key format
        
        # Sanitize value based on type
        if isinstance(value, dict):
            result[key] = _sanitize_dict(value, depth + 1, max_depth)
        elif isinstance(value, str):
            result[key] = _sanitize_string(value)
        elif isinstance(value, (int, float)):
            # Validate number range
            if abs(value) > 1e15:
                result[key] = 0  # Cap extreme values
            else:
                result[key] = value
        elif isinstance(value, bool):
            result[key] = value
        elif value is None:
            result[key] = None
        elif isinstance(value, list):
            result[key] = _sanitize_list(value, depth + 1, max_depth)
        else:
            # Convert unknown types to string
            result[key] = _sanitize_string(str(value)[:500])
        
        key_count += 1
    
    return result


def _sanitize_list(data: List, depth: int = 0, max_depth: int = 10) -> List:
    """
    Recursively sanitize list values.
    
    Args:
        data: List to sanitize
        depth: Current recursion depth
        max_depth: Maximum recursion depth
        
    Returns:
        Sanitized list
    """
    if depth > max_depth:
        return ["_error: Maximum nesting depth exceeded"]
    
    result = []
    item_count = 0
    
    for item in data:
        if item_count >= MAX_LIST_ITEMS:
            break
        
        if isinstance(item, dict):
            result.append(_sanitize_dict(item, depth + 1, max_depth))
        elif isinstance(item, str):
            result.append(_sanitize_string(item))
        elif isinstance(item, (int, float, bool, type(None))):
            result.append(item)
        elif isinstance(item, list):
            result.append(_sanitize_list(item, depth + 1, max_depth))
        else:
            result.append(_sanitize_string(str(item)[:500]))
        
        item_count += 1
    
    return result


def _sanitize_string(value: str) -> str:
    """
    Sanitize a string value.
    
    Args:
        value: String to sanitize
        
    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Limit length
    value = value[:MAX_STRING_LENGTH]
    
    # Strip dangerous patterns
    for pattern, replacement in DANGEROUS_PATTERNS:
        value = pattern.sub(replacement, value)
    
    # Remove control characters except newlines and tabs
    value = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', value)
    
    # Normalize whitespace
    value = re.sub(r'\s+', ' ', value).strip()
    
    return value


# =============================================================================
# URL Validation
# =============================================================================

def validate_url(url: str, max_length: int = MAX_URL_LENGTH) -> str:
    """
    Validate and sanitize a URL.
    
    Args:
        url: URL to validate
        max_length: Maximum URL length
        
    Returns:
        Validated URL
        
    Raises:
        ValueError: If URL is invalid
    """
    if not url:
        raise ValueError("URL cannot be empty")
    
    if len(url) > max_length:
        raise ValueError(f"URL exceeds maximum length ({max_length})")
    
    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL format: {e}")
    
    # Validate scheme
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}. Must be http or https")
    
    # Validate netloc (domain)
    if not parsed.netloc:
        raise ValueError("URL must have a domain")
    
    # Sanitize - remove potential XSS from query/fragment
    sanitized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        sanitized_query = _sanitize_string(parsed.query)[:1000]
        sanitized += f"?{sanitized_query}"
    if parsed.fragment:
        sanitized_fragment = _sanitize_string(parsed.fragment)[:500]
        sanitized += f"#{sanitized_fragment}"
    
    return sanitized


def validate_evidence_urls(urls: Optional[Dict[str, str]]) -> Dict[str, str]:
    """
    Validate a dictionary of evidence URLs.
    
    Args:
        urls: Dictionary mapping labels to URLs
        
    Returns:
        Validated URL dictionary
    """
    if not urls:
        return {}
    
    if not isinstance(urls, dict):
        raise MetadataValidationError("Evidence URLs must be a dictionary")
    
    result = {}
    for label, url in urls.items():
        if not isinstance(label, str):
            label = str(label)
        label = _sanitize_string(label)[:100]
        
        if not isinstance(url, str):
            continue
        
        try:
            validated_url = validate_url(url)
            result[label] = validated_url
        except ValueError:
            continue  # Skip invalid URLs
    
    return result


# =============================================================================
# Text Input Validation
# =============================================================================

def validate_text(
    text: str,
    min_length: int = 0,
    max_length: int = MAX_STRING_LENGTH,
    allow_html: bool = False
) -> str:
    """
    Validate and sanitize text input.
    
    Args:
        text: Text to validate
        min_length: Minimum text length
        max_length: Maximum text length
        allow_html: Whether to allow HTML (still sanitized if True)
        
    Returns:
        Validated text
        
    Raises:
        ValueError: If text is invalid
    """
    if not isinstance(text, str):
        text = str(text)
    
    text = text.strip()
    
    if len(text) < min_length:
        raise ValueError(f"Text must be at least {min_length} characters")
    
    if len(text) > max_length:
        raise ValueError(f"Text exceeds maximum length ({max_length})")
    
    if not allow_html:
        text = _sanitize_string(text)
    
    return text


def validate_description(description: Optional[str]) -> Optional[str]:
    """
    Validate a description field.
    
    Args:
        description: Description to validate
        
    Returns:
        Validated description or None
    """
    if not description:
        return None
    
    return validate_text(description, max_length=2000)


def validate_reason(reason: str) -> str:
    """
    Validate a reason field (e.g., for voiding envelopes).
    
    Args:
        reason: Reason to validate
        
    Returns:
        Validated reason
    """
    return validate_text(reason, min_length=1, max_length=500)


# =============================================================================
# Validators for Pydantic Models
# =============================================================================

def create_metadata_validator(max_size: int = MAX_METADATA_SIZE):
    """
    Create a validator function for Pydantic models.
    
    Usage:
        class MyModel(BaseModel):
            metadata: Dict[str, Any]
            
            _validate_metadata = validator('metadata', allow_reuse=True)(
                create_metadata_validator()
            )
    """
    def validator(v):
        return validate_metadata(v, max_size=max_size)
    return validator


def create_url_validator():
    """Create a URL validator for Pydantic models"""
    def validator(v):
        return validate_url(v)
    return validator

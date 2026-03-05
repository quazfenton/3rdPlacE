"""
Prometheus Metrics for Third Place Platform

Provides metrics for:
- Request counting and timing
- Business metrics (envelopes, claims, users)
- System metrics (cache, database)
- Error tracking

Usage:
    from services.metrics import metrics, track_request
    
    @track_request("envelope_created")
    def create_envelope(...):
        ...
    
    # Or manually
    metrics.envelope_created.inc()
    metrics.envelope_creation_time.observe(duration)
"""
import time
import logging
from typing import Optional, Dict, Any, Callable
from functools import wraps
from contextlib import contextmanager

try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Summary,
        CollectorRegistry, generate_latest,
        CONTENT_TYPE_LATEST, start_http_server
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Create stub classes
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    class Gauge:
        def __init__(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    class Summary:
        def __init__(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
    CONTENT_TYPE_LATEST = "text/plain"

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Prometheus metrics collector for Third Place Platform
    
    Metrics Categories:
    1. HTTP Metrics - Request counting, timing, status codes
    2. Business Metrics - Envelopes, claims, users, activities
    3. System Metrics - Cache, database, external services
    4. Error Metrics - Exception tracking by type
    """
    
    def __init__(self):
        if not PROMETHEUS_AVAILABLE:
            logger.warning("prometheus_client not installed. Metrics disabled.")
            self.enabled = False
            return
        
        self.enabled = True
        self.registry = CollectorRegistry()
        
        # =====================================================================
        # HTTP Metrics
        # =====================================================================
        
        self.http_requests_total = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status'],
            registry=self.registry
        )
        
        self.http_request_duration_seconds = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['method', 'endpoint'],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry
        )
        
        self.http_requests_in_progress = Gauge(
            'http_requests_in_progress',
            'HTTP requests currently being processed',
            ['method', 'endpoint'],
            registry=self.registry
        )
        
        self.http_request_size_bytes = Histogram(
            'http_request_size_bytes',
            'HTTP request size in bytes',
            ['method'],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000),
            registry=self.registry
        )
        
        self.http_response_size_bytes = Histogram(
            'http_response_size_bytes',
            'HTTP response size in bytes',
            ['method', 'endpoint'],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000),
            registry=self.registry
        )
        
        # =====================================================================
        # Business Metrics - Insurance Envelopes
        # =====================================================================
        
        self.envelopes_created_total = Counter(
            'envelopes_created_total',
            'Total insurance envelopes created',
            ['activity_class', 'jurisdiction'],
            registry=self.registry
        )
        
        self.envelopes_voided_total = Counter(
            'envelopes_voided_total',
            'Total insurance envelopes voided',
            ['reason'],
            registry=self.registry
        )
        
        self.envelopes_active = Gauge(
            'envelopes_active',
            'Currently active insurance envelopes',
            registry=self.registry
        )
        
        self.envelope_creation_time_seconds = Histogram(
            'envelope_creation_time_seconds',
            'Time to create an insurance envelope',
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry
        )
        
        self.envelope_attendance_cap = Histogram(
            'envelope_attendance_cap',
            'Attendance cap for insurance envelopes',
            buckets=(10, 25, 50, 100, 200, 500, 1000),
            registry=self.registry
        )
        
        # =====================================================================
        # Business Metrics - Activity Classification
        # =====================================================================
        
        self.activity_classifications_total = Counter(
            'activity_classifications_total',
            'Total activity classifications',
            ['activity_class', 'has_violation'],
            registry=self.registry
        )
        
        self.classification_time_seconds = Histogram(
            'classification_time_seconds',
            'Time to classify an activity',
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
            registry=self.registry
        )
        
        # =====================================================================
        # Business Metrics - Pricing
        # =====================================================================
        
        self.pricing_quotes_total = Counter(
            'pricing_quotes_total',
            'Total pricing quotes generated',
            registry=self.registry
        )
        
        self.pricing_quote_amount = Histogram(
            'pricing_quote_amount',
            'Insurance pricing quote amounts in USD',
            buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000),
            registry=self.registry
        )
        
        # =====================================================================
        # Business Metrics - Claims
        # =====================================================================
        
        self.claims_opened_total = Counter(
            'claims_opened_total',
            'Total insurance claims opened',
            ['claimant_type'],
            registry=self.registry
        )
        
        self.claims_closed_total = Counter(
            'claims_closed_total',
            'Total insurance claims closed',
            ['status'],  # approved, denied, paid
            registry=self.registry
        )
        
        self.claims_payout_total = Counter(
            'claims_payout_total',
            'Total insurance claim payouts in USD',
            registry=self.registry
        )
        
        # =====================================================================
        # Business Metrics - Users
        # =====================================================================
        
        self.users_registered_total = Counter(
            'users_registered_total',
            'Total users registered',
            ['role'],
            registry=self.registry
        )
        
        self.users_active = Gauge(
            'users_active',
            'Currently active users (logged in last 24h)',
            registry=self.registry
        )
        
        self.user_logins_total = Counter(
            'user_logins_total',
            'Total user logins',
            ['success'],  # true, false
            registry=self.registry
        )
        
        # =====================================================================
        # Business Metrics - Access Control
        # =====================================================================
        
        self.access_grants_created_total = Counter(
            'access_grants_created_total',
            'Total access grants created',
            ['lock_vendor'],
            registry=self.registry
        )
        
        self.access_grants_revoked_total = Counter(
            'access_grants_revoked_total',
            'Total access grants revoked',
            ['reason'],
            registry=self.registry
        )
        
        self.access_checkins_total = Counter(
            'access_checkins_total',
            'Total participant check-ins',
            ['result'],  # allowed, denied_capacity, denied_expired
            registry=self.registry
        )
        
        # =====================================================================
        # System Metrics - Cache
        # =====================================================================
        
        self.cache_operations_total = Counter(
            'cache_operations_total',
            'Total cache operations',
            ['operation', 'result'],  # get, set, delete / hit, miss
            registry=self.registry
        )
        
        self.cache_operation_duration_seconds = Histogram(
            'cache_operation_duration_seconds',
            'Cache operation duration',
            ['operation'],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
            registry=self.registry
        )
        
        self.cache_keys = Gauge(
            'cache_keys',
            'Number of keys in cache',
            registry=self.registry
        )
        
        # =====================================================================
        # System Metrics - Database
        # =====================================================================
        
        self.db_queries_total = Counter(
            'db_queries_total',
            'Total database queries',
            ['table', 'operation'],  # select, insert, update, delete
            registry=self.registry
        )
        
        self.db_query_duration_seconds = Histogram(
            'db_query_duration_seconds',
            'Database query duration',
            ['table'],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
            registry=self.registry
        )
        
        # =====================================================================
        # Error Metrics
        # =====================================================================
        
        self.exceptions_total = Counter(
            'exceptions_total',
            'Total exceptions raised',
            ['exception_type', 'endpoint'],
            registry=self.registry
        )
        
        self.validation_errors_total = Counter(
            'validation_errors_total',
            'Total validation errors',
            ['field', 'error_type'],
            registry=self.registry
        )
        
        # =====================================================================
        # Rate Limiting Metrics
        # =====================================================================
        
        self.rate_limit_hits_total = Counter(
            'rate_limit_hits_total',
            'Total rate limit hits',
            ['endpoint', 'limit_type'],
            registry=self.registry
        )
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def track_http_request(self, method: str, endpoint: str, status: int, 
                          duration: float, request_size: int = 0, 
                          response_size: int = 0):
        """Track HTTP request metrics"""
        if not self.enabled:
            return
        
        self.http_requests_total.labels(
            method=method, endpoint=endpoint, status=status
        ).inc()
        
        self.http_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(duration)
        
        if request_size > 0:
            self.http_request_size_bytes.labels(method=method).observe(request_size)
        
        if response_size > 0:
            self.http_response_size_bytes.labels(
                method=method, endpoint=endpoint
            ).observe(response_size)
    
    def track_envelope_created(self, activity_class: str, jurisdiction: str,
                               attendance_cap: int, duration: float):
        """Track envelope creation"""
        if not self.enabled:
            return
        
        self.envelopes_created_total.labels(
            activity_class=activity_class, jurisdiction=jurisdiction
        ).inc()
        
        self.envelope_creation_time_seconds.observe(duration)
        self.envelope_attendance_cap.observe(attendance_cap)
    
    def track_envelope_voided(self, reason: str):
        """Track envelope voiding"""
        if not self.enabled:
            return
        self.envelopes_voided_total.labels(reason=reason).inc()
    
    def track_activity_classification(self, activity_class: str, 
                                       has_violation: bool, duration: float):
        """Track activity classification"""
        if not self.enabled:
            return
        
        self.activity_classifications_total.labels(
            activity_class=activity_class, 
            has_violation=str(has_violation).lower()
        ).inc()
        
        self.classification_time_seconds.observe(duration)
    
    def track_pricing_quote(self, amount: float):
        """Track pricing quote"""
        if not self.enabled:
            return
        
        self.pricing_quotes_total.inc()
        self.pricing_quote_amount.observe(amount)
    
    def track_claim(self, event_type: str, claimant_type: str = None,
                   status: str = None, payout: float = None):
        """Track claim events"""
        if not self.enabled:
            return
        
        if event_type == 'opened' and claimant_type:
            self.claims_opened_total.labels(claimant_type=claimant_type).inc()
        elif event_type == 'closed' and status:
            self.claims_closed_total.labels(status=status).inc()
            if payout and payout > 0:
                self.claims_payout_total.inc(payout)
    
    def track_user_registration(self, role: str):
        """Track user registration"""
        if not self.enabled:
            return
        self.users_registered_total.labels(role=role).inc()
    
    def track_login(self, success: bool):
        """Track user login"""
        if not self.enabled:
            return
        self.user_logins_total.labels(success=str(success).lower()).inc()
    
    def track_access_grant(self, event_type: str, lock_vendor: str = None,
                          reason: str = None):
        """Track access grant events"""
        if not self.enabled:
            return
        
        if event_type == 'created' and lock_vendor:
            self.access_grants_created_total.labels(lock_vendor=lock_vendor).inc()
        elif event_type == 'revoked' and reason:
            self.access_grants_revoked_total.labels(reason=reason).inc()
    
    def track_checkin(self, result: str):
        """Track participant check-in"""
        if not self.enabled:
            return
        self.access_checkins_total.labels(result=result).inc()
    
    def track_cache_operation(self, operation: str, result: str, duration: float):
        """Track cache operations"""
        if not self.enabled:
            return
        
        self.cache_operations_total.labels(
            operation=operation, result=result
        ).inc()
        
        self.cache_operation_duration_seconds.labels(
            operation=operation
        ).observe(duration)
    
    def track_db_query(self, table: str, operation: str, duration: float):
        """Track database queries"""
        if not self.enabled:
            return
        
        self.db_queries_total.labels(
            table=table, operation=operation
        ).inc()
        
        self.db_query_duration_seconds.labels(table=table).observe(duration)
    
    def track_exception(self, exception_type: str, endpoint: str):
        """Track exceptions"""
        if not self.enabled:
            return
        self.exceptions_total.labels(
            exception_type=exception_type, endpoint=endpoint
        ).inc()
    
    def track_rate_limit(self, endpoint: str, limit_type: str):
        """Track rate limit hits"""
        if not self.enabled:
            return
        self.rate_limit_hits_total.labels(
            endpoint=endpoint, limit_type=limit_type
        ).inc()
    
    def get_metrics(self) -> str:
        """Get Prometheus-formatted metrics"""
        if not self.enabled:
            return "# Prometheus metrics not available"
        return generate_latest(self.registry).decode('utf-8')
    
    def get_content_type(self) -> str:
        """Get metrics content type"""
        return CONTENT_TYPE_LATEST


# Global metrics instance
metrics = MetricsCollector()


# =============================================================================
# Decorators
# =============================================================================

def track_request(endpoint_name: str):
    """
    Decorator to track request metrics
    
    Usage:
        @track_request("envelope_creation")
        async def create_envelope(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                if metrics.enabled:
                    metrics.track_exception(type(e).__name__, endpoint_name)
                raise
            finally:
                duration = time.time() - start_time
                # Additional tracking can be added here
        return wrapper
    return decorator


@contextmanager
def track_duration(metric_name: str, **labels):
    """
    Context manager to track operation duration
    
    Usage:
        with track_duration("envelope_creation_time"):
            create_envelope(...)
    """
    start_time = time.time()
    try:
        yield
    finally:
        duration = time.time() - start_time
        # Could be extended to record to specific metric


def get_metrics() -> str:
    """Get Prometheus-formatted metrics"""
    return metrics.get_metrics()


def get_metrics_content_type() -> str:
    """Get metrics content type"""
    return metrics.get_content_type()

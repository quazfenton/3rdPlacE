"""
Metrics API Router

Exposes Prometheus metrics endpoint.
"""
from fastapi import APIRouter, Depends, Response, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Metrics"])

# Security for metrics endpoint (optional)
security = HTTPBearer(auto_error=False)


@router.get("/metrics")
async def get_prometheus_metrics(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Prometheus metrics endpoint
    
    **Security:** 
    - In development: Open access
    - In production: Requires bearer token if METRICS_TOKEN is set
    
    **Metrics Categories:**
    - HTTP requests (count, duration, size)
    - Business metrics (envelopes, claims, users)
    - System metrics (cache, database)
    - Error tracking
    
    **Usage:**
    ```bash
    # Open access (development)
    curl http://localhost:8000/metrics
    
    # With token (production)
    curl http://localhost:8000/metrics \
      -H "Authorization: Bearer $METRICS_TOKEN"
    ```
    
    **Scrape with Prometheus:**
    ```yaml
    scrape_configs:
      - job_name: 'thirdplace'
        static_configs:
          - targets: ['localhost:8000']
        metrics_path: '/metrics'
    ```
    """
    # Check if metrics token is configured
    metrics_token = os.getenv("METRICS_TOKEN")
    
    if metrics_token:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Metrics endpoint requires authentication",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        if credentials.credentials != metrics_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid metrics token"
            )
    
    # Get metrics from collector
    from services.metrics import metrics
    
    if not metrics.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prometheus metrics not available. Install prometheus_client."
        )
    
    return Response(
        content=metrics.get_metrics(),
        media_type=metrics.get_content_type()
    )


@router.get("/health/metrics")
async def get_health_metrics():
    """
    Get health metrics in JSON format
    
    Returns simplified health metrics without requiring Prometheus.
    """
    from services.metrics import metrics
    
    if not metrics.enabled:
        return {
            "status": "metrics_disabled",
            "reason": "prometheus_client not installed"
        }
    
    # Get registry stats
    collectors = list(metrics.registry._names_to_collectors.values())
    
    return {
        "status": "healthy",
        "metrics_enabled": True,
        "total_collectors": len(collectors),
        "metric_types": {
            "counters": len([c for c in collectors if hasattr(c, 'inc')]),
            "gauges": len([c for c in collectors if hasattr(c, 'set')]),
            "histograms": len([c for c in collectors if hasattr(c, 'observe')])
        }
    }

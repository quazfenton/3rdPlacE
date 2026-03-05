"""
Audit Log API Router

Provides endpoints for querying and retrieving audit logs.
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
import logging

from config.database import get_db
from services.auth_service import get_current_active_user, User, admin_only
from services.audit_service import AuditService
from middleware.rate_limiter import read_rate_limit
from repositories.base_repository import RepositoryFactory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Audit Logs"])


@router.get(
    "/logs",
    response_model=Dict[str, Any],
    summary="Query audit logs"
)
@read_rate_limit
async def query_audit_logs(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    actor_id: Optional[str] = Query(None, description="Filter by actor ID"),
    action: Optional[str] = Query(None, description="Filter by action"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db)
):
    """
    Query audit logs with filters
    
    **Permissions:** Admin only
    
    **Filters:**
    - `event_type`: Filter by event type (e.g., "envelope_created")
    - `entity_type`: Filter by entity type (e.g., "envelope", "user")
    - `entity_id`: Filter by specific entity ID
    - `actor_id`: Filter by actor who performed the action
    - `action`: Filter by action type (e.g., "create", "void")
    - `start_date`: Filter logs after this date
    - `end_date`: Filter logs before this date
    
    **Pagination:**
    - `limit`: Maximum results (default: 100, max: 500)
    - `offset`: Offset for pagination (default: 0)
    """
    try:
        repos = RepositoryFactory(db)
        
        # Build query
        query = db.query(repos.audit_logs.model).order_by(
            repos.audit_logs.model.created_at.desc()
        )
        
        # Apply filters
        if event_type:
            query = query.filter(repos.audit_logs.model.event_type == event_type)
        if entity_type:
            query = query.filter(repos.audit_logs.model.entity_type == entity_type)
        if entity_id:
            query = query.filter(repos.audit_logs.model.entity_id == entity_id)
        if actor_id:
            query = query.filter(repos.audit_logs.model.actor_id == actor_id)
        if action:
            query = query.filter(repos.audit_logs.model.action == action)
        if start_date:
            query = query.filter(repos.audit_logs.model.created_at >= start_date)
        if end_date:
            query = query.filter(repos.audit_logs.model.created_at <= end_date)
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        logs = query.offset(offset).limit(limit).all()
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "logs": [
                {
                    "id": str(log.id),
                    "event_type": log.event_type,
                    "entity_type": log.entity_type,
                    "entity_id": str(log.entity_id),
                    "actor_id": log.actor_id,
                    "action": log.action,
                    "reason": log.reason,
                    "metadata": log.metadata,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "created_at": log.created_at.isoformat() if log.created_at else None
                }
                for log in logs
            ]
        }
        
    except Exception as e:
        logger.error(f"Error querying audit logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query audit logs"
        )


@router.get(
    "/logs/entity/{entity_type}/{entity_id}",
    response_model=List[Dict[str, Any]],
    summary="Get audit logs for entity"
)
@read_rate_limit
async def get_entity_audit_logs(
    entity_type: str,
    entity_id: str,
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get audit logs for a specific entity
    
    **Permissions:** Any authenticated user (for their own entities)
    
    Returns the audit trail for a specific entity (e.g., envelope, user, claim).
    """
    try:
        logs = AuditService.get_audit_logs_for_entity(
            db=db,
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit
        )
        
        return [
            {
                "id": str(log.id),
                "event_type": log.event_type,
                "entity_type": log.entity_type,
                "entity_id": str(log.entity_id),
                "actor_id": log.actor_id,
                "action": log.action,
                "reason": log.reason,
                "metadata": log.metadata,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ]
        
    except Exception as e:
        logger.error(f"Error getting entity audit logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get entity audit logs"
        )


@router.get(
    "/logs/recent",
    response_model=Dict[str, Any],
    summary="Get recent audit logs"
)
@read_rate_limit
async def get_recent_audit_logs(
    hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db)
):
    """
    Get recent audit logs
    
    **Permissions:** Admin only
    
    Returns audit logs from the specified time period.
    """
    try:
        logs = AuditService.get_recent_audit_logs(
            db=db,
            hours=hours,
            limit=limit
        )
        
        return {
            "time_period_hours": hours,
            "count": len(logs),
            "logs": [
                {
                    "id": str(log.id),
                    "event_type": log.event_type,
                    "entity_type": log.entity_type,
                    "entity_id": str(log.entity_id),
                    "actor_id": log.actor_id,
                    "action": log.action,
                    "created_at": log.created_at.isoformat() if log.created_at else None
                }
                for log in logs
            ]
        }
        
    except Exception as e:
        logger.error(f"Error getting recent audit logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get recent audit logs"
        )


@router.get(
    "/logs/summary",
    response_model=Dict[str, Any],
    summary="Get audit logs summary"
)
@read_rate_limit
async def get_audit_logs_summary(
    hours: int = Query(24, ge=1, le=168, description="Hours to summarize"),
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db)
):
    """
    Get summary statistics for audit logs
    
    **Permissions:** Admin only
    
    Returns aggregated statistics about audit events.
    """
    try:
        summary = AuditService.get_audit_logs_summary(
            db=db,
            hours=hours
        )
        
        return summary
        
    except Exception as e:
        logger.error(f"Error getting audit logs summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get audit logs summary"
        )


@router.get(
    "/logs/by-actor/{actor_id}",
    response_model=List[Dict[str, Any]],
    summary="Get audit logs by actor"
)
@read_rate_limit
async def get_actor_audit_logs(
    actor_id: str,
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db)
):
    """
    Get audit logs for a specific actor
    
    **Permissions:** Admin only
    
    Returns all audit logs for actions performed by a specific user.
    """
    try:
        logs = AuditService.get_audit_logs_by_actor(
            db=db,
            actor_id=actor_id,
            limit=limit
        )
        
        return [
            {
                "id": str(log.id),
                "event_type": log.event_type,
                "entity_type": log.entity_type,
                "entity_id": str(log.entity_id),
                "action": log.action,
                "reason": log.reason,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ]
        
    except Exception as e:
        logger.error(f"Error getting actor audit logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get actor audit logs"
        )


@router.get(
    "/logs/event-types",
    response_model=List[str],
    summary="Get unique event types"
)
@read_rate_limit
async def get_event_types(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get list of unique event types in the audit log
    
    Useful for building filters in the UI.
    """
    try:
        from sqlalchemy import distinct
        
        event_types = db.query(
            distinct(repos.audit_logs.model.event_type)
        ).order_by(
            repos.audit_logs.model.event_type
        ).all()
        
        return [et[0] for et in event_types if et[0]]
        
    except Exception as e:
        logger.error(f"Error getting event types: {e}", exc_info=True)
        # Return common event types as fallback
        return [
            "envelope_created",
            "envelope_activated",
            "envelope_voided",
            "access_grant_created",
            "access_revoked",
            "user_login",
            "user_created",
            "claim_processed"
        ]

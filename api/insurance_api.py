from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
import logging

from config.database import get_db
from services.insurance_envelope_service import InsuranceEnvelopeService
from services.activity_classification_engine import ActivityClassificationEngine
from services.pricing_engine import InsurancePricingEngine
from services.lock_integration import AccessGrantService
from services.audit_service import AuditService
from services.auth_service import get_current_active_user, User
from services.domain_events import EventDispatcher, EventType
from repositories.base_repository import RepositoryFactory
from middleware.rate_limiter import standard_rate_limit, heavy_operation_rate_limit, read_rate_limit
from utils.exceptions import (
    ValidationError, InsuranceValidationError, CoverageError,
    ClassificationError, NotFoundError, ConflictError
)

logger = logging.getLogger(__name__)

# Initialize APIRouter
router = APIRouter(prefix="/ial", tags=["Insurance"])


# Pydantic models with enhanced validation
class ClassifyActivityRequest(BaseModel):
    """Request model for activity classification"""
    space_id: str = Field(..., description="Space UUID")
    declared_activity: str = Field(..., min_length=1, max_length=500, description="Activity description")
    equipment: List[str] = Field(default_factory=list, description="Equipment used")
    alcohol: bool = Field(default=False, description="Whether alcohol is present")
    minors_present: bool = Field(default=False, description="Whether minors will be present")
    attendance_cap: int = Field(default=10, ge=1, le=10000, description="Expected attendance")

    @validator('declared_activity')
    def validate_activity(cls, v):
        if not v or not v.strip():
            raise ValueError("Activity description cannot be empty")
        return v.strip()


class ClassifyActivityResult(BaseModel):
    """Response model for activity classification"""
    activity_class: str
    activity_class_id: str
    risk_score: float
    allowed: bool
    required_limits: Dict[str, Any]
    violation_reasons: List[str] = []
    equipment_risk: float = 1.0
    space_hazard: float = 0.0


class QuotePricingRequest(BaseModel):
    """Request model for insurance pricing quote"""
    activity_class_id: str
    space_id: str
    attendance_cap: int = Field(ge=1, le=10000)
    duration_minutes: int = Field(ge=1, le=1440)
    jurisdiction: str = Field(..., pattern=r'^[A-Z]{2}(-[A-Z]{2})?$')


class QuotePricingResult(BaseModel):
    """Response model for insurance pricing quote"""
    price: float
    currency: str
    breakdown: Dict[str, float]
    calculated_risk_score: float


class CreateEnvelopeRequest(BaseModel):
    """Request model for creating an insurance envelope"""
    policy_root_id: str
    activity_class_id: str
    space_id: str
    steward_id: str = Field(..., min_length=1, max_length=100)
    platform_entity_id: str = Field(..., min_length=1, max_length=100)
    attendance_cap: int = Field(ge=1, le=10000)
    duration_minutes: int = Field(ge=1, le=720)
    valid_from: datetime
    valid_until: datetime
    event_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    alcohol: bool = False
    minors_present: bool = False

    @validator('valid_until')
    def validate_dates(cls, v, values):
        if 'valid_from' in values and v <= values['valid_from']:
            raise ValueError("valid_until must be after valid_from")
        return v


class CreateEnvelopeResult(BaseModel):
    """Response model for created insurance envelope"""
    envelope_id: str
    status: str
    certificate_url: str
    valid_from: datetime
    valid_until: datetime
    attendance_cap: int


class VerifyCoverageResult(BaseModel):
    """Response model for coverage verification"""
    valid: bool
    coverage_limits: Dict[str, Any]
    valid_until: Optional[datetime]
    status: str
    error_code: Optional[str] = None


class EnvelopeResponse(BaseModel):
    """Detailed envelope response"""
    id: str
    status: str
    policy_number: Optional[str]
    activity_class: Optional[str]
    space_id: str
    steward_id: str
    attendance_cap: int
    duration_minutes: int
    alcohol: bool
    minors_present: bool
    valid_from: datetime
    valid_until: datetime
    coverage_limits: Dict[str, Any]
    certificate_url: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class CreateAccessGrantRequest(BaseModel):
    """Request for creating access grant"""
    envelope_id: str
    lock_id: str
    lock_vendor: str = Field(default="generic")


class AccessGrantResult(BaseModel):
    """Access grant creation result"""
    grant_id: str
    access_type: str
    access_payload: Dict[str, Any]
    valid_from: datetime
    valid_until: datetime


# Activity Classification Endpoint
@router.post(
    "/activity/classify",
    response_model=ClassifyActivityResult,
    tags=["Activity Classification"]
)
@standard_rate_limit
async def classify_activity(
    request: ClassifyActivityRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Classify an activity and determine its risk profile.
    
    **Risk Classes:**
    - `passive`: Low risk (board games, reading, discussions)
    - `light_physical`: Medium risk (yoga, dance, cooking)
    - `tool_based`: Higher risk (woodworking, repairs)
    
    **Important:** If the activity violates restrictions (alcohol/minors),
    the response will have `allowed=false` with violation reasons.
    """
    try:
        result = ActivityClassificationEngine.classify_activity(
            db=db,
            space_id=request.space_id,
            declared_activity=request.declared_activity,
            equipment=request.equipment,
            alcohol=request.alcohol,
            minors_present=request.minors_present,
            attendance_cap=request.attendance_cap
        )

        return ClassifyActivityResult(
            activity_class=result.get('activity_class_slug', 'unknown'),
            activity_class_id=result.get('activity_class_id', ''),
            risk_score=result.get('risk_score', 0.0),
            allowed=not result.get('prohibited', False),
            required_limits=result.get('required_limits', {}),
            violation_reasons=result.get('violation_reasons', []),
            equipment_risk=result.get('equipment_risk', 1.0),
            space_hazard=result.get('space_hazard', 0.0)
        )
    except (ValidationError, InsuranceValidationError, ClassificationError) as e:
        logger.warning(f"Classification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.message) if hasattr(e, 'message') else str(e)
        )
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e.message) if hasattr(e, 'message') else str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected classification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Classification service unavailable"
        )


# Pricing Quote Endpoint
@router.post(
    "/pricing/quote",
    response_model=QuotePricingResult,
    tags=["Pricing"]
)
@standard_rate_limit
async def quote_pricing(
    request: QuotePricingRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Calculate insurance premium for a specific coverage scenario.
    
    **Pricing Factors:**
    - Activity Class risk level
    - Duration (longer = more expensive)
    - Attendance (higher = more expensive)
    - Jurisdiction (regional regulations)
    - Space hazard rating
    """
    try:
        result = InsurancePricingEngine.quote_pricing(
            db=db,
            activity_class_id=request.activity_class_id,
            space_id=request.space_id,
            attendance_cap=request.attendance_cap,
            duration_minutes=request.duration_minutes,
            jurisdiction=request.jurisdiction
        )

        return QuotePricingResult(
            price=result['final_price'],
            currency=result['currency'],
            breakdown=result['breakdown'],
            calculated_risk_score=result.get('calculated_risk_score', 0.0)
        )
    except (ValidationError, NotFoundError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.message) if hasattr(e, 'message') else str(e)
        )
    except Exception as e:
        logger.error(f"Pricing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pricing service unavailable"
        )


# Create Envelope Endpoint
@router.post(
    "/envelopes",
    response_model=CreateEnvelopeResult,
    tags=["Envelopes"]
)
@heavy_operation_rate_limit
async def create_insurance_envelope(
    request: CreateEnvelopeRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    req: Request = None
):
    """
    Create a new insurance coverage envelope.
    
    **Process:**
    1. Validates all inputs
    2. Checks for overlapping envelopes
    3. Validates activity compliance
    4. Creates and activates envelope
    5. Generates certificate
    
    **Note:** Envelopes cannot overlap in time for the same space.
    """
    client_ip = req.client.host if req and req.client else None
    
    try:
        envelope = InsuranceEnvelopeService.create_envelope(
            db=db,
            policy_root_id=request.policy_root_id,
            activity_class_id=request.activity_class_id,
            space_id=request.space_id,
            steward_id=request.steward_id,
            platform_entity_id=request.platform_entity_id,
            attendance_cap=request.attendance_cap,
            duration_minutes=request.duration_minutes,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
            event_metadata=request.event_metadata,
            alcohol=request.alcohol,
            minors_present=request.minors_present,
            actor_id=str(current_user.id)
        )

        # Log creation
        AuditService.log_envelope_created(db, str(envelope.id), str(current_user.id), client_ip)

        return CreateEnvelopeResult(
            envelope_id=str(envelope.id),
            status=envelope.status,
            certificate_url=envelope.certificate_url or "",
            valid_from=envelope.valid_from,
            valid_until=envelope.valid_until,
            attendance_cap=envelope.attendance_cap
        )
    except (ValidationError, InsuranceValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.message) if hasattr(e, 'message') else str(e)
        )
    except ConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e.message) if hasattr(e, 'message') else str(e)
        )
    except Exception as e:
        logger.error(f"Envelope creation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create envelope"
        )


# List Envelopes Endpoint
@router.get(
    "/envelopes",
    response_model=List[EnvelopeResponse],
    tags=["Envelopes"]
)
@read_rate_limit
async def list_envelopes(
    space_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    steward_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    List insurance envelopes with optional filters.
    
    **Filters:**
    - `space_id`: Filter by space
    - `status`: Filter by status (pending, active, voided, expired, claim_open)
    - `steward_id`: Filter by steward
    """
    repos = RepositoryFactory(db)
    
    if space_id:
        envelopes = repos.envelopes.get_envelopes_for_space(space_id, status)
    elif steward_id:
        envelopes = repos.envelopes.get_envelopes_for_steward(steward_id, status)
    else:
        envelopes = repos.envelopes.list(limit=limit, offset=offset)
    
    return [
        EnvelopeResponse(
            id=str(e.id),
            status=e.status,
            policy_number=e.policy_root.policy_number if e.policy_root else None,
            activity_class=e.activity_class.slug if e.activity_class else None,
            space_id=str(e.space_id),
            steward_id=e.steward_id,
            attendance_cap=e.attendance_cap,
            duration_minutes=e.duration_minutes,
            alcohol=e.alcohol,
            minors_present=e.minors_present,
            valid_from=e.valid_from,
            valid_until=e.valid_until,
            coverage_limits=e.coverage_limits or {},
            certificate_url=e.certificate_url,
            created_at=e.created_at
        )
        for e in envelopes
    ]


# Get Envelope Details Endpoint
@router.get(
    "/envelopes/{envelope_id}",
    response_model=EnvelopeResponse,
    tags=["Envelopes"]
)
@read_rate_limit
async def get_envelope(
    envelope_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific envelope.
    """
    result = InsuranceEnvelopeService.get_envelope_details(db, envelope_id)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Envelope not found"
        )
    
    return EnvelopeResponse(**result)


# Verify Coverage Endpoint
@router.get(
    "/envelopes/{envelope_id}/verify",
    response_model=VerifyCoverageResult,
    tags=["Coverage"]
)
@read_rate_limit
async def verify_coverage(
    envelope_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Verify if an insurance envelope is currently valid and active.
    """
    try:
        envelope = InsuranceEnvelopeService.get_active_envelope(db, envelope_id)

        if not envelope:
            return VerifyCoverageResult(
                valid=False,
                coverage_limits={},
                valid_until=None,
                status="not_found",
                error_code="ENVELOPE_NOT_FOUND"
            )

        if not InsuranceEnvelopeService.is_envelope_valid(envelope):
            return VerifyCoverageResult(
                valid=False,
                coverage_limits=envelope.coverage_limits or {},
                valid_until=envelope.valid_until,
                status=envelope.status,
                error_code="ENVELOPE_NOT_VALID"
            )

        return VerifyCoverageResult(
            valid=True,
            coverage_limits=envelope.coverage_limits or {},
            valid_until=envelope.valid_until,
            status=envelope.status
        )
    except Exception as e:
        logger.error(f"Verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification failed"
        )


# Void Envelope Endpoint
@router.post(
    "/envelopes/{envelope_id}/void",
    tags=["Coverage"]
)
@heavy_operation_rate_limit
async def void_envelope(
    envelope_id: str,
    reason: str = Query(..., min_length=1, max_length=500),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Void/deactivate an insurance envelope.
    
    **Important:**
    - Immediately revokes all associated access grants
    - Cannot be undone
    - Requires a reason for audit purposes
    """
    try:
        envelope = InsuranceEnvelopeService.deactivate_envelope(
            db=db,
            envelope_id=envelope_id,
            reason=reason,
            actor_id=str(current_user.id)
        )

        return {
            "envelope_id": str(envelope.id),
            "status": envelope.status,
            "reason": reason,
            "voided_at": datetime.now(timezone.utc).isoformat()
        }
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e.message) if hasattr(e, 'message') else str(e)
        )
    except Exception as e:
        logger.error(f"Void error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to void envelope"
        )


# Create Access Grant Endpoint
@router.post(
    "/envelopes/{envelope_id}/access-grants",
    response_model=AccessGrantResult,
    tags=["Access Control"]
)
@heavy_operation_rate_limit
async def create_access_grant(
    envelope_id: str,
    request: CreateAccessGrantRequest,
    valid_hours: int = Query(default=24, ge=1, le=168),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Create an access grant for an envelope.
    
    The access grant allows physical access to the space during the event.
    """
    try:
        # Get envelope to determine validity period
        repos = RepositoryFactory(db)
        envelope = repos.envelopes.get_or_raise(envelope_id)
        
        if envelope.status != 'active':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Envelope status is {envelope.status}, must be 'active'"
            )
        
        # Get access grant service from app state
        from main import app
        access_grant_service = app.state.access_grant_service
        
        # Create access grant
        result = await access_grant_service.create_access_grant(
            db=db,
            envelope_id=envelope_id,
            lock_id=request.lock_id,
            lock_vendor=request.lock_vendor,
            valid_from=envelope.valid_from,
            valid_until=envelope.valid_until,
            attendance_cap=envelope.attendance_cap,
            actor_id=str(current_user.id)
        )

        return AccessGrantResult(**result)
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e.message) if hasattr(e, 'message') else str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Access grant creation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create access grant"
        )


# Get Activity Classes Endpoint
@router.get(
    "/activity-classes",
    tags=["Activity Classification"]
)
@read_rate_limit
async def get_activity_classes(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get all available activity classes.
    """
    return ActivityClassificationEngine.get_available_classes(db)


# Health check for IAL
@router.get("/health")
async def health_check():
    """IAL service health check"""
    return {"status": "healthy", "service": "Insurance Abstraction Layer"}

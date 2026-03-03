from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import uuid

from config.database import get_db
from services.insurance_envelope_service import InsuranceEnvelopeService
from services.activity_classification_engine import ActivityClassificationEngine, ActivityProfile
from services.pricing_engine import InsurancePricingEngine
from models.insurance_models import InsuranceEnvelope
from services.auth_service import get_current_active_user, User
from utils.exceptions import ValidationError, InsuranceValidationError, CoverageError, ClassificationError


# Initialize APIRouter with enhanced documentation
router = APIRouter(
    prefix="/ial",
    tags=["insurance"]
)

# Add OpenAPI tags for better organization
router.openapi_tags = [
    {
        "name": "insurance",
        "description": "Insurance envelope management operations",
    },
    {
        "name": "Activity Classification",
        "description": "Classify activities and determine risk profiles",
    },
    {
        "name": "Pricing",
        "description": "Get insurance pricing quotes",
    },
    {
        "name": "Coverage",
        "description": "Verify and manage coverage status",
    },
]


# Pydantic models for request/response with enhanced validation
class ClassifyActivityRequest(BaseModel):
    """Request model for activity classification"""
    space_id: str
    declared_activity: str
    equipment: Optional[list] = []
    alcohol: bool = False
    minors_present: bool = False
    attendance_cap: int = 10


class ClassifyActivityResult(BaseModel):
    """Response model for activity classification"""
    activity_class: str
    risk_score: float
    allowed: bool
    required_limits: Dict[str, Any]
    violation_reasons: Optional[list] = []


class QuotePricingRequest(BaseModel):
    """Request model for insurance pricing quote"""
    activity_class_id: str
    space_id: str
    attendance_cap: int
    duration_minutes: int
    jurisdiction: str


class QuotePricingResult(BaseModel):
    """Response model for insurance pricing quote"""
    price: float
    currency: str
    breakdown: Dict[str, float]


class CreateEnvelopeRequest(BaseModel):
    """Request model for creating an insurance envelope"""
    policy_root_id: str
    activity_class_id: str
    space_id: str
    steward_id: str
    platform_entity_id: str
    attendance_cap: int
    duration_minutes: int
    valid_from: datetime
    valid_until: datetime
    event_metadata: Optional[Dict[str, Any]] = {}
    alcohol: bool = False
    minors_present: bool = False


class CreateEnvelopeResult(BaseModel):
    """Response model for created insurance envelope"""
    envelope_id: str
    status: str
    certificate_url: str


class VerifyCoverageResult(BaseModel):
    """Response model for coverage verification"""
    valid: bool
    coverage_limits: Dict[str, Any]
    valid_until: datetime


@router.post(
    "/ial/activity/classify",
    response_model=ClassifyActivityResult,
    tags=["Activity Classification"],
    summary="Classify an activity",
    description="""
Classify a declared activity and determine its risk profile.

This endpoint analyzes:
- **Activity type**: Matches against known activity patterns
- **Equipment**: Assesses risk from tools/equipment used
- **Alcohol**: Whether alcohol is present (affects classification)
- **Minors**: Whether minors will be present
- **Attendance**: Number of expected participants

**Risk Classes:**
- `passive`: Low risk (board games, reading, discussions)
- `light_physical`: Medium risk (yoga, dance, cooking)
- `tool_based`: Higher risk (woodworking, repairs)
    """,
    responses={
        200: {"description": "Activity classified successfully"},
        400: {"description": "Invalid activity or space configuration"},
        500: {"description": "Internal server error"},
    }
)
async def classify_activity(request: ClassifyActivityRequest, current_user: User = Depends(get_current_active_user), db=Depends(get_db)):
    """
    Classify an activity and determine its risk profile
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
            risk_score=result.get('risk_score', 0.0),
            allowed=not result.get('prohibited', True),
            required_limits=result.get('required_limits', {}),
            violation_reasons=result.get('violation_reasons', [])
        )
    except (ValidationError, InsuranceValidationError, CoverageError, ClassificationError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        ) from e


@router.post(
    "/ial/pricing/quote",
    response_model=QuotePricingResult,
    tags=["Pricing"],
    summary="Get insurance pricing quote",
    description="""
Calculate insurance premium for a specific coverage scenario.

**Pricing Factors:**
- **Activity Class**: Base rate determined by risk level
- **Duration**: Longer events cost more (with diminishing returns)
- **Attendance**: Higher attendance increases premium
- **Jurisdiction**: Regional regulations affect pricing
- **Space Risk**: Hazard rating of the venue

**Base Rates:**
- Passive activities: $10.00
- Light physical: $15.00
- Tool-based: $25.00
    """,
    responses={
        200: {"description": "Pricing quote generated successfully"},
        400: {"description": "Invalid pricing parameters"},
        500: {"description": "Internal server error"},
    }
)
async def quote_pricing(request: QuotePricingRequest, current_user: User = Depends(get_current_active_user), db=Depends(get_db)):
    """
    Get a pricing quote for insurance coverage
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
            price=result['price'],
            currency=result['currency'],
            breakdown=result['breakdown']
        )
    except (ValidationError, InsuranceValidationError, CoverageError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pricing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        ) from e


@router.post(
    "/ial/envelopes",
    response_model=CreateEnvelopeResult,
    tags=["insurance"],
    summary="Create insurance envelope",
    description="""
Create a new insurance coverage envelope for a physical gathering.

An insurance envelope is the atomic unit of coverage that wraps a specific gathering.

**Requirements:**
- Active policy root
- Valid activity class
- Space risk profile
- Future valid_from date (max 12 hours duration)

**Process:**
1. Validates all inputs
2. Checks policy, activity class, and space exist
3. Validates activity compliance (alcohol/minors restrictions)
4. Creates envelope with 'pending' status
5. Automatically activates envelope and generates certificate
    """,
    responses={
        200: {"description": "Envelope created and activated successfully"},
        400: {"description": "Validation error - invalid inputs or restrictions violated"},
        500: {"description": "Internal server error"},
    }
)
async def create_insurance_envelope(request: CreateEnvelopeRequest, current_user: User = Depends(get_current_active_user), db=Depends(get_db)):
    """
    Create a new insurance envelope
    """
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
            minors_present=request.minors_present
        )

        return CreateEnvelopeResult(
            envelope_id=str(envelope.id),
            status=envelope.status,
            certificate_url=envelope.certificate_url
        )
    except (ValidationError, InsuranceValidationError, CoverageError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Envelope creation error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        ) from e


@router.get(
    "/ial/envelopes/{envelope_id}/verify",
    response_model=VerifyCoverageResult,
    tags=["Coverage"],
    summary="Verify coverage",
    description="""
Verify if an insurance envelope is currently valid and active.

**Validation Checks:**
- Envelope exists and is in 'active' status
- Current time is within valid_from and valid_until window
- Envelope has not been voided or expired

**Use Cases:**
- Pre-event coverage verification
- Access control integration
- Real-time coverage status checks
    """,
    responses={
        200: {"description": "Coverage verification result"},
        400: {"description": "Invalid envelope ID"},
        500: {"description": "Internal server error"},
    }
)
async def verify_coverage(envelope_id: str, current_user: User = Depends(get_current_active_user), db=Depends(get_db)):
    """
    Verify if an insurance envelope is valid
    """
    try:
        envelope = InsuranceEnvelopeService.get_active_envelope(db, envelope_id)

        if envelope and InsuranceEnvelopeService.is_envelope_valid(envelope):
            return VerifyCoverageResult(
                valid=True,
                coverage_limits=envelope.coverage_limits or {},
                valid_until=envelope.valid_until
            )
        else:
            return VerifyCoverageResult(
                valid=False,
                coverage_limits={},
                valid_until=datetime.min
            )
    except (ValidationError, InsuranceValidationError, CoverageError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Verification error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        ) from e


@router.post(
    "/ial/envelopes/{envelope_id}/void",
    tags=["Coverage"],
    summary="Void insurance envelope",
    description="""
Void/deactivate an insurance envelope.

**Important:**
- Voiding an envelope immediately revokes all associated access grants
- This action cannot be undone
- A reason must be provided for audit purposes

**Common Reasons:**
- Safety incident
- Capacity violation
- Policy violation
- Emergency situation

**Side Effects:**
- All active access grants are revoked
- Lock systems are notified (if integrated)
- Audit log entry is created
    """,
    responses={
        200: {"description": "Envelope voided successfully"},
        400: {"description": "Invalid envelope ID or already voided"},
        500: {"description": "Internal server error"},
    }
)
async def void_envelope(envelope_id: str, reason: str, current_user: User = Depends(get_current_active_user), db=Depends(get_db)):
    """
    Void an insurance envelope
    """
    try:
        envelope = InsuranceEnvelopeService.deactivate_envelope(db, envelope_id, reason)

        return {
            "envelope_id": str(envelope.id),
            "status": envelope.status,
            "reason": reason
        }
    except (ValidationError, InsuranceValidationError, CoverageError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Void error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        ) from e


# Health check endpoint
@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Insurance Abstraction Layer"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
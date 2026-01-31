from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel
import uuid

from config.database import get_db
from services.insurance_envelope_service import InsuranceEnvelopeService
from services.activity_classification_engine import ActivityClassificationEngine, ActivityProfile
from services.pricing_engine import InsurancePricingEngine
from models.insurance_models import InsuranceEnvelope


# Initialize FastAPI app
app = FastAPI(title="Third Place Insurance Abstraction Layer", version="1.0.0")


# Pydantic models for request/response
class ClassifyActivityRequest(BaseModel):
    space_id: str
    declared_activity: str
    equipment: Optional[list] = []
    alcohol: bool = False
    minors_present: bool = False
    attendance_cap: int = 10


class ClassifyActivityResult(BaseModel):
    activity_class: str
    risk_score: float
    allowed: bool
    required_limits: Dict[str, Any]
    violation_reasons: Optional[list] = []


class QuotePricingRequest(BaseModel):
    activity_class_id: str
    space_id: str
    attendance_cap: int
    duration_minutes: int
    jurisdiction: str


class QuotePricingResult(BaseModel):
    price: float
    currency: str
    breakdown: Dict[str, float]


class CreateEnvelopeRequest(BaseModel):
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
    envelope_id: str
    status: str
    certificate_url: str


class VerifyCoverageResult(BaseModel):
    valid: bool
    coverage_limits: Dict[str, Any]
    valid_until: datetime


@app.post("/ial/activity/classify", response_model=ClassifyActivityResult)
async def classify_activity(request: ClassifyActivityRequest, db=Depends(get_db)):
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error classifying activity: {str(e)}"
        )


@app.post("/ial/pricing/quote", response_model=QuotePricingResult)
async def quote_pricing(request: QuotePricingRequest, db=Depends(get_db)):
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error calculating pricing: {str(e)}"
        )


@app.post("/ial/envelopes", response_model=CreateEnvelopeResult)
async def create_insurance_envelope(request: CreateEnvelopeRequest, db=Depends(get_db)):
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error creating insurance envelope: {str(e)}"
        )


@app.get("/ial/envelopes/{envelope_id}/verify", response_model=VerifyCoverageResult)
async def verify_coverage(envelope_id: str, db=Depends(get_db)):
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error verifying coverage: {str(e)}"
        )


@app.post("/ial/envelopes/{envelope_id}/void")
async def void_envelope(envelope_id: str, reason: str, db=Depends(get_db)):
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error voiding envelope: {str(e)}"
        )


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Insurance Abstraction Layer"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
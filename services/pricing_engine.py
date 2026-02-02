from decimal import Decimal
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from models.insurance_models import InsurancePricing, ActivityClass, SpaceRiskProfile, PolicyRoot
from services.activity_classification_engine import ActivityClassificationEngine


class InsurancePricingEngine:
    """
    Insurance Pricing Engine
    Calculates insurance costs based on multiple risk factors
    """
    
    # Base rates per activity class
    BASE_RATES = {
        'passive': Decimal('10.00'),
        'light_physical': Decimal('15.00'),
        'tool_based': Decimal('25.00')
    }
    
    # Default factors
    DEFAULT_DURATION_FACTOR = Decimal('1.00')
    DEFAULT_ATTENDANCE_FACTOR = Decimal('1.00')
    DEFAULT_JURISDICTION_FACTOR = Decimal('1.00')
    DEFAULT_RISK_FACTOR = Decimal('1.00')
    
    @staticmethod
    def calculate_pricing(
        db: Session,
        activity_class_id: str,
        space_id: str,
        attendance_cap: int,
        duration_minutes: int,
        jurisdiction: str,
        risk_score: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculate insurance pricing based on all factors
        """
        # Get activity class
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.id == activity_class_id
        ).first()
        
        if not activity_class:
            raise ValueError(f"Activity class {activity_class_id} not found")
        
        # Get space risk profile
        space_profile = db.query(SpaceRiskProfile).filter(
            SpaceRiskProfile.space_id == space_id
        ).first()
        
        if not space_profile:
            raise ValueError(f"Space profile {space_id} not found")
        
        # Calculate base rate
        base_rate = InsurancePricingEngine._get_base_rate(activity_class.slug)
        
        # Calculate factors
        duration_factor = InsurancePricingEngine._calculate_duration_factor(duration_minutes)
        attendance_factor = InsurancePricingEngine._calculate_attendance_factor(attendance_cap)
        jurisdiction_factor = InsurancePricingEngine._calculate_jurisdiction_factor(jurisdiction)
        
        # If risk score not provided, estimate from activity class
        if risk_score is None:
            risk_score = float(activity_class.base_risk_score)
        
        risk_factor = InsurancePricingEngine._calculate_risk_factor(risk_score, space_profile)
        
        # Calculate final price
        final_price = base_rate * duration_factor * attendance_factor * jurisdiction_factor * risk_factor
        
        return {
            'base_rate': float(base_rate),
            'duration_factor': float(duration_factor),
            'attendance_factor': float(attendance_factor),
            'jurisdiction_factor': float(jurisdiction_factor),
            'risk_factor': float(risk_factor),
            'final_price': float(final_price),
            'breakdown': {
                'base_rate': float(base_rate),
                'duration_component': float(base_rate * duration_factor) - float(base_rate),
                'attendance_component': float(base_rate * attendance_factor) - float(base_rate),
                'jurisdiction_component': float(base_rate * jurisdiction_factor) - float(base_rate),
                'risk_component': float(base_rate * risk_factor) - float(base_rate)
            }
        }
    
    @staticmethod
    def quote_pricing(
        db: Session,
        activity_class_id: str,
        space_id: str,
        attendance_cap: int,
        duration_minutes: int,
        jurisdiction: str
    ) -> Dict[str, Any]:
        """
        Generate a pricing quote for insurance coverage
        """
        # First classify the activity to get risk score
        # For this implementation, we'll assume the activity has already been classified
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.id == activity_class_id
        ).first()
        
        if not activity_class:
            raise ValueError(f"Activity class {activity_class_id} not found")
        
        space_profile = db.query(SpaceRiskProfile).filter(
            SpaceRiskProfile.space_id == space_id
        ).first()
        
        if not space_profile:
            raise ValueError(f"Space profile {space_id} not found")
        
        # Calculate risk score based on space and activity
        risk_score = float(activity_class.base_risk_score)
        if space_profile.hazard_rating:
            # Adjust risk score based on space hazard
            risk_score = min(1.0, risk_score + float(space_profile.hazard_rating) / 10.0)
        
        # Calculate pricing
        pricing_result = InsurancePricingEngine.calculate_pricing(
            db, activity_class_id, space_id, attendance_cap, 
            duration_minutes, jurisdiction, risk_score
        )
        
        return {
            'price': pricing_result['final_price'],
            'currency': 'USD',
            'breakdown': pricing_result['breakdown'],
            'estimated_risk_score': risk_score
        }
    
    @staticmethod
    def save_pricing_snapshot(
        db: Session,
        envelope_id: str,
        pricing_data: Dict[str, Any]
    ) -> InsurancePricing:
        """
        Save a pricing snapshot for an insurance envelope
        """
        pricing = InsurancePricing(
            envelope_id=envelope_id,
            base_rate=Decimal(str(pricing_data['base_rate'])),
            duration_factor=Decimal(str(pricing_data['duration_factor'])),
            attendance_factor=Decimal(str(pricing_data['attendance_factor'])),
            jurisdiction_factor=Decimal(str(pricing_data['jurisdiction_factor'])),
            risk_factor=Decimal(str(pricing_data['risk_factor'])),
            final_price=Decimal(str(pricing_data['final_price']))
        )
        
        db.add(pricing)
        db.commit()
        db.refresh(pricing)
        
        return pricing
    
    @staticmethod
    def _get_base_rate(activity_slug: str) -> Decimal:
        """
        Get the base rate for an activity class
        """
        return InsurancePricingEngine.BASE_RATES.get(
            activity_slug, 
            InsurancePricingEngine.BASE_RATES['passive']
        )
    
    @staticmethod
    def _calculate_duration_factor(duration_minutes: int) -> Decimal:
        """
        Calculate the duration factor based on event length
        Longer events have higher risk and therefore higher cost
        """
        # Normalize to 3-hour base (180 minutes)
        base_duration = 180  # minutes
        normalized_duration = duration_minutes / base_duration
        
        # Apply diminishing returns - longer events cost proportionally less per minute
        if normalized_duration <= 1.0:
            # For events up to 3 hours, linear increase
            factor = Decimal(str(normalized_duration))
        else:
            # For events longer than 3 hours, slower increase
            factor = Decimal('1.0') + (Decimal(str(normalized_duration)) - Decimal('1.0')) * Decimal('0.7')
        
        # Ensure minimum factor of 0.5 and maximum of 3.0
        factor = max(factor, Decimal('0.5'))
        factor = min(factor, Decimal('3.0'))
        
        return factor
    
    @staticmethod
    def _calculate_attendance_factor(attendance_cap: int) -> Decimal:
        """
        Calculate the attendance factor based on number of participants
        More people mean higher risk and therefore higher cost
        """
        if attendance_cap <= 10:
            # Base rate for small groups
            factor = Decimal('1.0')
        elif attendance_cap <= 20:
            # Small increase for medium groups
            factor = Decimal('1.2')
        elif attendance_cap <= 50:
            # Larger increase for large groups
            factor = Decimal('1.5')
        else:
            # Significant increase for very large groups
            factor = Decimal('2.0')
        
        return factor
    
    @staticmethod
    def _calculate_jurisdiction_factor(jurisdiction: str) -> Decimal:
        """
        Calculate the jurisdiction factor based on location
        Different regions have different risk profiles and regulations
        """
        # Define jurisdiction multipliers
        jurisdiction_multipliers = {
            'US-CA': Decimal('1.1'),  # California tends to have higher insurance costs
            'US-NY': Decimal('1.2'),  # New York
            'US-TX': Decimal('1.0'),  # Texas
            'US-FL': Decimal('1.15'), # Florida
            'US-IL': Decimal('1.05'), # Illinois
            'US-WA': Decimal('1.0'),  # Washington
            'US-OR': Decimal('1.0'),  # Oregon
            'US-CO': Decimal('1.0'),  # Colorado
            'US-AZ': Decimal('1.0'),  # Arizona
            'US-NV': Decimal('1.05'), # Nevada
            'US-MI': Decimal('1.0'),  # Michigan
            'US-VA': Decimal('1.0'),  # Virginia
            'US-GA': Decimal('1.05'), # Georgia
            'US-NC': Decimal('1.0'),  # North Carolina
            'US-OH': Decimal('1.0'),  # Ohio
            'US-IN': Decimal('1.0'),  # Indiana
            'US-TN': Decimal('1.0'),  # Tennessee
            'US-KY': Decimal('1.0'),  # Kentucky
            'US-AL': Decimal('1.0'),  # Alabama
            'US-MS': Decimal('1.0'),  # Mississippi
            'US-LA': Decimal('1.1'),  # Louisiana
            'US-AR': Decimal('1.0'),  # Arkansas
            'US-OK': Decimal('1.0'),  # Oklahoma
            'US-KS': Decimal('1.0'),  # Kansas
            'US-NE': Decimal('1.0'),  # Nebraska
            'US-SD': Decimal('1.0'),  # South Dakota
            'US-ND': Decimal('1.0'),  # North Dakota
            'US-MT': Decimal('1.0'),  # Montana
            'US-ID': Decimal('1.0'),  # Idaho
            'US-WY': Decimal('1.0'),  # Wyoming
            'US-UT': Decimal('1.0'),  # Utah
            'US-NM': Decimal('1.0'),  # New Mexico
            'US-AK': Decimal('1.1'),  # Alaska
            'US-HI': Decimal('1.15'), # Hawaii
            'US-MA': Decimal('1.15'), # Massachusetts
            'US-CT': Decimal('1.15'), # Connecticut
            'US-RI': Decimal('1.1'),  # Rhode Island
            'US-NJ': Decimal('1.2'),  # New Jersey
            'US-PA': Decimal('1.1'),  # Pennsylvania
            'US-DE': Decimal('1.1'),  # Delaware
            'US-MD': Decimal('1.1'),  # Maryland
            'US-DC': Decimal('1.15'), # District of Columbia
            'US-VT': Decimal('1.05'), # Vermont
            'US-NH': Decimal('1.05'), # New Hampshire
            'US-ME': Decimal('1.05'), # Maine
            
            # Default for unknown jurisdictions
            'default': Decimal('1.0')
        }
        
        return jurisdiction_multipliers.get(jurisdiction, jurisdiction_multipliers['default'])
    
    @staticmethod
    def _calculate_risk_factor(risk_score: float, space_profile: SpaceRiskProfile) -> Decimal:
        """
        Calculate the risk factor based on the combined risk score
        """
        # Base risk factor from activity classification
        base_risk_factor = Decimal(str(max(0.5, min(3.0, 1.0 + risk_score))))
        
        # Adjust based on space hazard rating
        space_hazard_factor = Decimal('1.0')
        if space_profile.hazard_rating is not None:
            hazard_rating = float(space_profile.hazard_rating)
            # Higher hazard rating increases the risk factor
            space_hazard_factor = Decimal(str(1.0 + (hazard_rating / 5.0)))
        
        # Combine factors
        combined_factor = base_risk_factor * space_hazard_factor
        
        # Cap the factor to prevent extremely high prices
        combined_factor = min(combined_factor, Decimal('5.0'))
        
        return combined_factor
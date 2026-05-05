from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
import logging

from models.insurance_models import InsurancePricing, ActivityClass, SpaceRiskProfile
from utils.exceptions import ValidationError, NotFoundError

logger = logging.getLogger(__name__)


class InsurancePricingEngine:
    """
    Insurance Pricing Engine
    Calculates insurance costs based on multiple risk factors
    
    Improvements:
    - Proper breakdown calculation that adds up correctly
    - Input validation
    - Configurable base rates
    - Maximum price cap
    """

    # Base rates per activity class (in USD)
    BASE_RATES = {
        'passive': Decimal('10.00'),
        'light_physical': Decimal('15.00'),
        'tool_based': Decimal('25.00')
    }

    # Pricing limits
    MIN_PRICE = Decimal('1.00')
    MAX_PRICE = Decimal('10000.00')

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
        Calculate insurance pricing based on all factors.
        
        Returns detailed breakdown where all components add up to final price.
        """
        # Validate inputs
        if attendance_cap <= 0:
            raise ValidationError("attendance_cap must be greater than 0")
        if duration_minutes <= 0:
            raise ValidationError("duration_minutes must be greater than 0")
        if duration_minutes > 1440:
            raise ValidationError("duration_minutes cannot exceed 1440 (24 hours)")

        # Get activity class
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.id == activity_class_id
        ).first()

        if not activity_class:
            raise NotFoundError(f"Activity class {activity_class_id} not found")

        # Get space risk profile
        space_profile = db.query(SpaceRiskProfile).filter(
            SpaceRiskProfile.space_id == space_id
        ).first()

        if not space_profile:
            raise NotFoundError(f"Space profile {space_id} not found")

        # Calculate base rate
        base_rate = InsurancePricingEngine._get_base_rate(activity_class.slug)

        # Calculate factors
        duration_factor = InsurancePricingEngine._calculate_duration_factor(duration_minutes)
        attendance_factor = InsurancePricingEngine._calculate_attendance_factor(attendance_cap)
        jurisdiction_factor = InsurancePricingEngine._calculate_jurisdiction_factor(jurisdiction)

        # If risk score not provided, estimate from activity class
        if risk_score is None:
            risk_score = float(activity_class.base_risk_score) if activity_class.base_risk_score else 0.1
        
        if space_profile.hazard_rating:
            # Adjust risk score based on space hazard
            risk_score = min(1.0, risk_score + float(space_profile.hazard_rating) / 10.0)

        risk_factor = InsurancePricingEngine._calculate_risk_factor(risk_score, space_profile)

        # Calculate final price using multiplicative model
        # final = base * duration * attendance * jurisdiction * risk
        final_price = base_rate * duration_factor * attendance_factor * jurisdiction_factor * risk_factor
        
        # Apply min/max caps
        final_price = max(InsurancePricingEngine.MIN_PRICE, min(InsurancePricingEngine.MAX_PRICE, final_price))
        final_price = final_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Calculate breakdown properly - each component shows incremental cost
        # Using multiplicative model:
        # base_component = base_rate
        # duration_component = base_rate * duration_factor - base_rate
        # attendance_component = (base_rate * duration_factor) * attendance_factor - (base_rate * duration_factor)
        # etc.
        
        price_after_duration = base_rate * duration_factor
        price_after_attendance = price_after_duration * attendance_factor
        price_after_jurisdiction = price_after_attendance * jurisdiction_factor
        price_after_risk = price_after_jurisdiction * risk_factor
        
        # Final capped price
        final_capped = max(InsurancePricingEngine.MIN_PRICE, min(InsurancePricingEngine.MAX_PRICE, price_after_risk))
        final_capped = final_capped.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Calculate proportional breakdown
        total_factors = float(duration_factor * attendance_factor * jurisdiction_factor * risk_factor)
        
        if total_factors > 0:
            # Each component's proportion of the total multiplier
            duration_portion = (float(duration_factor) - 1) / total_factors if total_factors > 1 else 0
            attendance_portion = (float(attendance_factor) - 1) * float(duration_factor) / total_factors if total_factors > 1 else 0
            jurisdiction_portion = (float(jurisdiction_factor) - 1) * float(duration_factor * attendance_factor) / total_factors if total_factors > 1 else 0
            risk_portion = (float(risk_factor) - 1) * float(duration_factor * attendance_factor * jurisdiction_factor) / total_factors if total_factors > 1 else 0
            
            base_portion = 1 / total_factors
            
            # Convert to dollar amounts
            base_component = float(final_capped) * base_portion
            duration_component = float(final_capped) * duration_portion
            attendance_component = float(final_capped) * attendance_portion
            jurisdiction_component = float(final_capped) * jurisdiction_portion
            risk_component = float(final_capped) * risk_portion
        else:
            base_component = float(final_capped)
            duration_component = 0
            attendance_component = 0
            jurisdiction_component = 0
            risk_component = 0

        return {
            'base_rate': float(base_rate),
            'duration_factor': float(duration_factor),
            'attendance_factor': float(attendance_factor),
            'jurisdiction_factor': float(jurisdiction_factor),
            'risk_factor': float(risk_factor),
            'final_price': float(final_capped),
            'currency': 'USD',
            'breakdown': {
                'base_component': round(base_component, 2),
                'duration_component': round(duration_component, 2),
                'attendance_component': round(attendance_component, 2),
                'jurisdiction_component': round(jurisdiction_component, 2),
                'risk_component': round(risk_component, 2),
                'total': round(
                    base_component + duration_component + attendance_component + 
                    jurisdiction_component + risk_component, 2
                )
            },
            'calculated_risk_score': round(risk_score, 2)
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
        Generate a pricing quote for insurance coverage.
        """
        return InsurancePricingEngine.calculate_pricing(
            db=db,
            activity_class_id=activity_class_id,
            space_id=space_id,
            attendance_cap=attendance_cap,
            duration_minutes=duration_minutes,
            jurisdiction=jurisdiction
        )

    @staticmethod
    def save_pricing_snapshot(
        db: Session,
        envelope_id: str,
        pricing_data: Dict[str, Any]
    ) -> InsurancePricing:
        """
        Save a pricing snapshot for an insurance envelope.
        """
        pricing = InsurancePricing(
            envelope_id=envelope_id,
            base_rate=Decimal(str(pricing_data['base_rate'])),
            duration_factor=Decimal(str(pricing_data['duration_factor'])),
            attendance_factor=Decimal(str(pricing_data['attendance_factor'])),
            jurisdiction_factor=Decimal(str(pricing_data['jurisdiction_factor'])),
            risk_factor=Decimal(str(pricing_data['risk_factor'])),
            final_price=Decimal(str(pricing_data['final_price'])),
            currency=pricing_data.get('currency', 'USD')
        )

        db.add(pricing)
        db.commit()
        db.refresh(pricing)
        
        logger.info(f"Saved pricing snapshot for envelope {envelope_id}: ${pricing_data['final_price']}")

        return pricing

    @staticmethod
    def _get_base_rate(activity_slug: str) -> Decimal:
        """
        Get the base rate for an activity class.
        """
        return InsurancePricingEngine.BASE_RATES.get(
            activity_slug,
            InsurancePricingEngine.BASE_RATES['passive']
        )

    @staticmethod
    def _calculate_duration_factor(duration_minutes: int) -> Decimal:
        """
        Calculate the duration factor based on event length.
        
        Pricing model:
        - Base duration: 3 hours (180 minutes)
        - Events up to 3 hours: linear scaling
        - Events longer than 3 hours: diminishing returns (70% rate)
        - Minimum factor: 0.5
        - Maximum factor: 3.0
        """
        base_duration = 180  # 3 hours in minutes
        normalized_duration = duration_minutes / base_duration

        if normalized_duration <= 1.0:
            # Linear scaling for events up to 3 hours
            factor = Decimal(str(normalized_duration))
        else:
            # Diminishing returns for longer events
            excess = Decimal(str(normalized_duration)) - Decimal('1.0')
            factor = Decimal('1.0') + (excess * Decimal('0.7'))

        # Apply bounds
        factor = max(factor, Decimal('0.5'))
        factor = min(factor, Decimal('3.0'))

        return factor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @staticmethod
    def _calculate_attendance_factor(attendance_cap: int) -> Decimal:
        """
        Calculate the attendance factor based on number of participants.
        
        Pricing tiers:
        - 1-10 attendees: base rate (1.0)
        - 11-20 attendees: +20% (1.2)
        - 21-50 attendees: +50% (1.5)
        - 51+ attendees: +100% (2.0)
        """
        if attendance_cap <= 10:
            factor = Decimal('1.0')
        elif attendance_cap <= 20:
            factor = Decimal('1.2')
        elif attendance_cap <= 50:
            factor = Decimal('1.5')
        else:
            factor = Decimal('2.0')

        return factor

    @staticmethod
    def _calculate_jurisdiction_factor(jurisdiction: str) -> Decimal:
        """
        Calculate the jurisdiction factor based on location.
        
        Different regions have different risk profiles and regulations.
        Uses a dictionary for easy updates without code changes.
        """
        # Jurisdiction multipliers - can be moved to config/database
        jurisdiction_multipliers = {
            # High cost jurisdictions
            'US-CA': Decimal('1.15'),
            'US-NY': Decimal('1.25'),
            'US-FL': Decimal('1.15'),
            'US-HI': Decimal('1.15'),
            'US-MA': Decimal('1.15'),
            'US-CT': Decimal('1.15'),
            'US-DC': Decimal('1.15'),
            'US-NJ': Decimal('1.20'),
            'US-LA': Decimal('1.10'),
            'US-AK': Decimal('1.10'),
            
            # Medium cost jurisdictions
            'US-IL': Decimal('1.05'),
            'US-WA': Decimal('1.05'),
            'US-OR': Decimal('1.05'),
            'US-PA': Decimal('1.05'),
            'US-DE': Decimal('1.05'),
            'US-MD': Decimal('1.05'),
            'US-NV': Decimal('1.05'),
            'US-GA': Decimal('1.05'),
            'US-VT': Decimal('1.05'),
            'US-NH': Decimal('1.05'),
            'US-ME': Decimal('1.05'),
            
            # Standard cost jurisdictions (default)
            'default': Decimal('1.0')
        }

        return jurisdiction_multipliers.get(
            jurisdiction,
            jurisdiction_multipliers['default']
        )

    @staticmethod
    def _calculate_risk_factor(risk_score: float, space_profile: SpaceRiskProfile) -> Decimal:
        """
        Calculate the risk factor based on the combined risk score.
        
        Formula: base_risk_factor * space_hazard_factor
        - base_risk_factor: 1.0 + risk_score (capped at 2.0)
        - space_hazard_factor: 1.0 + (hazard_rating / 5.0)
        - Combined cap: 5.0
        """
        # Base risk factor from activity classification
        base_risk_factor = Decimal(str(max(0.5, min(2.0, 1.0 + risk_score))))

        # Adjust based on space hazard rating
        space_hazard_factor = Decimal('1.0')
        if space_profile.hazard_rating is not None:
            hazard_rating = float(space_profile.hazard_rating)
            space_hazard_factor = Decimal(str(1.0 + (hazard_rating / 5.0)))

        # Combine factors
        combined_factor = base_risk_factor * space_hazard_factor

        # Cap the factor
        combined_factor = min(combined_factor, Decimal('5.0'))

        return combined_factor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @staticmethod
    def update_base_rates(rates: Dict[str, float]) -> None:
        """
        Update base rates dynamically.
        Useful for A/B testing or regional pricing adjustments.
        """
        for slug, rate in rates.items():
            if rate < 0:
                raise ValidationError(f"Base rate cannot be negative: {rate}")
            InsurancePricingEngine.BASE_RATES[slug] = Decimal(str(rate))
        
        logger.info(f"Updated base rates: {rates}")

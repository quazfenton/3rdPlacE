from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from models.insurance_models import ActivityClass, SpaceRiskProfile
from utils.exceptions import ClassificationError, ValidationError
import logging
import re

logger = logging.getLogger(__name__)


class ActivityClassificationEngine:
    """
    Activity Classification Engine (ACE)
    Determines risk classification for activities based on multiple factors
    
    IMPORTANT: This engine preserves restriction violations rather than bypassing them.
    If an activity violates alcohol/minors restrictions, it returns prohibited=True
    with violation_reasons instead of finding an alternative class.
    """

    # Risk thresholds for classification
    RISK_THRESHOLDS = {
        'passive': 0.3,
        'light_physical': 0.6,
        'tool_based': 1.0
    }

    # Equipment risk multipliers
    EQUIPMENT_RISK_MULTIPLIERS = {
        'sharp_tools': 1.3,
        'power_tools': 1.5,
        'heating_equipment': 1.2,
        'chemicals': 1.4,
        'heavy_equipment': 1.3,
        'saw': 1.4,
        'hammer': 1.1,
        'drill': 1.3,
        'welding': 1.6,
        'soldering': 1.2
    }

    # Activity patterns for classification
    ACTIVITY_PATTERNS = {
        'passive': [
            'board games', 'card games', 'chess', 'checkers', 'scrabble',
            'reading', 'book club', 'discussion', 'philosophy', 'language exchange',
            'movie night', 'silent study', 'writing', 'knitting', 'sewing',
            'painting', 'drawing', 'crafting', 'storytelling', 'meditation',
            'lecture', 'presentation', 'workshop', 'seminar', 'meeting'
        ],
        'light_physical': [
            'yoga', 'dance', 'stretching', 'exercise', 'fitness',
            'cooking', 'baking', 'mixology', 'bartending',
            'arts and crafts', 'pottery', 'ceramics',
            'photography', 'filmmaking', 'music', 'singing',
            'pilates', 'tai chi', 'aerobics', 'zumba'
        ],
        'tool_based': [
            'repair', 'fixing', 'woodworking', 'carpentry', 'metalworking',
            'electronics', 'soldering', 'welding', 'machining',
            'bike repair', 'car maintenance', 'gardening tools',
            'power tools', 'drill', 'saw', 'grinder', 'lathe',
            'construction', 'demolition', 'renovation'
        ]
    }

    @staticmethod
    def classify_activity(
        db: Session,
        space_id: str,
        declared_activity: str,
        equipment: Optional[List[str]] = None,
        alcohol: bool = False,
        minors_present: bool = False,
        attendance_cap: int = 10
    ) -> Dict[str, Any]:
        """
        Classify an activity and determine its risk profile.
        
        CRITICAL: This method preserves restriction violations. If the classified
        activity doesn't allow alcohol or minors but they are present, it returns
        prohibited=True with violation_reasons. It does NOT find an alternative
        class that allows the violations.
        
        Returns:
            Dict with keys:
            - activity_class_id: UUID of matched class (or None)
            - activity_class_slug: slug of matched class
            - risk_score: calculated risk score (0.0-1.0)
            - required_limits: coverage limits for this class
            - prohibited: True if activity violates restrictions
            - violation_reasons: list of violation descriptions
        """
        if equipment is None:
            equipment = []

        # Validate inputs
        if not declared_activity or not declared_activity.strip():
            raise ValidationError("declared_activity cannot be empty")
        
        if attendance_cap <= 0:
            raise ValidationError("attendance_cap must be greater than 0")

        # Get space risk profile
        space_profile = db.query(SpaceRiskProfile).filter(
            SpaceRiskProfile.space_id == space_id
        ).first()

        if not space_profile:
            raise ClassificationError(f"Space profile {space_id} not found")

        # Determine base activity class from declared activity
        suggested_slug = ActivityClassificationEngine._determine_base_class_slug(declared_activity)
        
        # Get the activity class from database
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.slug == suggested_slug
        ).first()

        if not activity_class:
            # Try to find closest match
            activity_class = ActivityClassificationEngine._find_closest_class_in_db(db, suggested_slug)
            
            if not activity_class:
                # Last resort: use passive as default
                activity_class = db.query(ActivityClass).filter(
                    ActivityClass.slug == 'passive'
                ).first()
                
                if not activity_class:
                    raise ClassificationError(
                        "No activity classes defined in the system. "
                        "Please seed the database with activity classes."
                    )

        # Calculate risk modifiers
        base_risk = float(activity_class.base_risk_score) if activity_class.base_risk_score else 0.1
        risk_modifiers = ActivityClassificationEngine._calculate_risk_modifiers(
            base_risk,
            space_profile,
            equipment,
            alcohol,
            minors_present,
            attendance_cap
        )

        # Calculate final risk score
        final_risk_score = ActivityClassificationEngine._apply_modifiers(
            base_risk,
            risk_modifiers
        )

        # Validate against class restrictions - THIS IS CRITICAL
        # We do NOT find an alternative class - we report violations
        violations = ActivityClassificationEngine._validate_against_class(
            activity_class, alcohol, minors_present, equipment
        )

        return {
            'activity_class_id': str(activity_class.id),
            'activity_class_slug': activity_class.slug,
            'risk_score': round(final_risk_score, 2),
            'required_limits': activity_class.default_limits or {},
            'prohibited': len(violations) > 0,
            'violation_reasons': violations,
            'equipment_risk': risk_modifiers.get('equipment', 1.0),
            'space_hazard': float(space_profile.hazard_rating) if space_profile.hazard_rating else 0.0
        }

    @staticmethod
    def _determine_base_class_slug(declared_activity: str) -> str:
        """
        Determine the base activity class slug based on declared activity.
        Uses pattern matching with word boundaries to avoid false positives.
        """
        activity_lower = declared_activity.lower()
        
        # Score each class based on pattern matches
        class_scores = {
            'passive': 0,
            'light_physical': 0,
            'tool_based': 0
        }
        
        for class_name, patterns in ActivityClassificationEngine.ACTIVITY_PATTERNS.items():
            for pattern in patterns:
                # Use word boundary matching to avoid false positives
                # e.g., "cooking" matches but "book cooking" (cookbook) doesn't
                pattern_regex = r'\b' + re.escape(pattern) + r'\b'
                if re.search(pattern_regex, activity_lower):
                    class_scores[class_name] += 1
        
        # Return class with highest score
        max_score = max(class_scores.values())
        if max_score == 0:
            return 'passive'  # Default to passive if no matches
        
        # Return first class with max score (priority order)
        for class_name in ['tool_based', 'light_physical', 'passive']:
            if class_scores[class_name] == max_score:
                return class_name
        
        return 'passive'

    @staticmethod
    def _find_closest_class_in_db(db: Session, suggested_slug: str) -> Optional[ActivityClass]:
        """
        Find the closest matching activity class in the database.
        Returns None if no suitable match found.
        """
        # First try exact match
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.slug == suggested_slug
        ).first()

        if activity_class:
            return activity_class

        # Try partial match
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.slug.contains(suggested_slug)
        ).first()

        if activity_class:
            return activity_class

        return None

    @staticmethod
    def _calculate_risk_modifiers(
        base_risk: float,
        space_profile: SpaceRiskProfile,
        equipment: List[str],
        alcohol: bool,
        minors_present: bool,
        attendance_cap: int
    ) -> Dict[str, float]:
        """
        Calculate risk modifiers based on various factors.
        """
        modifiers = {}

        # Space hazard modifier (adds to risk)
        if space_profile.hazard_rating is not None:
            hazard = float(space_profile.hazard_rating)
            modifiers['space_hazard'] = hazard / 10.0  # Scale down contribution

        # Equipment risk modifier (multiplicative)
        equipment_risk = 1.0
        for equip in equipment:
            equip_lower = equip.lower() if equip else ''
            # Check exact match first
            if equip_lower in ActivityClassificationEngine.EQUIPMENT_RISK_MULTIPLIERS:
                equipment_risk *= ActivityClassificationEngine.EQUIPMENT_RISK_MULTIPLIERS[equip_lower]
            else:
                # Check partial match
                for known_equip, multiplier in ActivityClassificationEngine.EQUIPMENT_RISK_MULTIPLIERS.items():
                    if known_equip in equip_lower:
                        equipment_risk *= multiplier
                        break
        
        if equipment_risk > 1.0:
            modifiers['equipment'] = equipment_risk

        # Alcohol modifier (increases risk)
        if alcohol:
            modifiers['alcohol'] = 1.4

        # Minors modifier (increases supervision risk)
        if minors_present:
            modifiers['minors'] = 1.2

        # Attendance modifier (higher attendance = higher risk)
        if attendance_cap > 50:
            modifiers['attendance'] = min(2.5, 1.0 + (attendance_cap - 10) * 0.03)
        elif attendance_cap > 20:
            modifiers['attendance'] = min(1.8, 1.0 + (attendance_cap - 10) * 0.02)
        elif attendance_cap > 10:
            modifiers['attendance'] = min(1.3, 1.0 + (attendance_cap - 5) * 0.01)

        return modifiers

    @staticmethod
    def _apply_modifiers(base_risk: float, modifiers: Dict[str, float]) -> float:
        """
        Apply risk modifiers to base risk score.
        Space hazard adds to risk, other modifiers multiply.
        """
        final_risk = base_risk

        for modifier_name, modifier_value in modifiers.items():
            if modifier_name == 'space_hazard':
                # Space hazard adds to risk
                final_risk = min(1.0, final_risk + modifier_value)
            else:
                # Other modifiers multiply
                final_risk = min(1.0, final_risk * modifier_value)

        return final_risk

    @staticmethod
    def _validate_against_class(
        activity_class: ActivityClass,
        alcohol: bool,
        minors_present: bool,
        equipment: List[str]
    ) -> List[str]:
        """
        Validate the activity against class restrictions.
        Returns list of violation reasons (empty if no violations).
        
        CRITICAL: This method reports violations, it does not try to find
        an alternative class that allows the violations.
        """
        violations = []

        # Check alcohol restriction
        if alcohol and not activity_class.allows_alcohol:
            violations.append(
                f"Activity class '{activity_class.slug}' does not permit alcohol"
            )

        # Check minors restriction
        if minors_present and not activity_class.allows_minors:
            violations.append(
                f"Activity class '{activity_class.slug}' does not permit minors"
            )

        # Check prohibited equipment
        if activity_class.prohibited_equipment:
            prohibited = activity_class.prohibited_equipment
            if isinstance(prohibited, dict):
                prohibited = list(prohibited.keys())
            elif isinstance(prohibited, list):
                pass
            else:
                prohibited = []
            
            for equip in equipment:
                equip_lower = equip.lower() if equip else ''
                for prohibited_item in prohibited:
                    prohibited_lower = prohibited_item.lower() if prohibited_item else ''
                    if prohibited_lower in equip_lower or equip_lower in prohibited_lower:
                        violations.append(
                            f"Equipment '{equip}' is prohibited for activity class '{activity_class.slug}'"
                        )
                        break

        return violations

    @staticmethod
    def get_available_classes(db: Session) -> List[Dict[str, Any]]:
        """
        Get all available activity classes with their restrictions.
        """
        classes = db.query(ActivityClass).all()
        return [
            {
                'id': str(cls.id),
                'slug': cls.slug,
                'description': cls.description,
                'base_risk_score': float(cls.base_risk_score) if cls.base_risk_score else 0.0,
                'allows_alcohol': cls.allows_alcohol,
                'allows_minors': cls.allows_minors,
                'default_limits': cls.default_limits or {},
                'prohibited_equipment': cls.prohibited_equipment or {}
            }
            for cls in classes
        ]

    @staticmethod
    def validate_equipment(equipment: List[str]) -> Dict[str, Any]:
        """
        Validate equipment list and return risk assessment.
        """
        known_equipment = set(ActivityClassificationEngine.EQUIPMENT_RISK_MULTIPLIERS.keys())
        unknown = []
        high_risk = []
        
        for equip in equipment:
            equip_lower = equip.lower() if equip else ''
            is_known = False
            for known in known_equipment:
                if known in equip_lower or equip_lower in known:
                    is_known = True
                    multiplier = ActivityClassificationEngine.EQUIPMENT_RISK_MULTIPLIERS.get(known, 1.0)
                    if multiplier >= 1.4:
                        high_risk.append(equip)
                    break
            
            if not is_known:
                unknown.append(equip)
        
        return {
            'valid': len(unknown) == 0,
            'unknown_equipment': unknown,
            'high_risk_equipment': high_risk,
            'equipment_count': len(equipment)
        }


class ActivityProfile:
    """
    Represents the output of activity classification.
    This class is kept for backward compatibility.
    """
    def __init__(
        self,
        activity_class_id: Optional[str],
        activity_class_slug: Optional[str],
        risk_score: float,
        required_limits: Dict[str, Any],
        prohibited: bool,
        violation_reasons: Optional[List[str]] = None
    ):
        self.activity_class_id = activity_class_id
        self.activity_class_slug = activity_class_slug
        self.risk_score = risk_score
        self.required_limits = required_limits
        self.prohibited = prohibited
        self.violation_reasons = violation_reasons or []
    
    @classmethod
    def from_classification_result(cls, result: Dict[str, Any]) -> 'ActivityProfile':
        """Create ActivityProfile from classification result dict"""
        return cls(
            activity_class_id=result.get('activity_class_id'),
            activity_class_slug=result.get('activity_class_slug'),
            risk_score=result.get('risk_score', 0.0),
            required_limits=result.get('required_limits', {}),
            prohibited=result.get('prohibited', False),
            violation_reasons=result.get('violation_reasons', [])
        )

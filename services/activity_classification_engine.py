from typing import Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from models.insurance_models import ActivityClass, SpaceRiskProfile
from utils.exceptions import ClassificationError


class ActivityClassificationEngine:
    """
    Activity Classification Engine (ACE)
    Determines risk classification for activities based on multiple factors
    """

    # Risk thresholds
    RISK_THRESHOLDS = {
        'passive': 0.3,
        'light_physical': 0.6,
        'tool_based': 0.8
    }

    # Equipment risk multipliers
    EQUIPMENT_RISK_MULTIPLIERS = {
        'sharp_tools': 1.3,
        'power_tools': 1.5,
        'heating_equipment': 1.2,
        'chemicals': 1.4,
        'heavy_equipment': 1.3
    }

    @staticmethod
    def classify_activity(
        db: Session,
        space_id: str,
        declared_activity: str,
        equipment: Optional[list] = None,
        alcohol: bool = False,
        minors_present: bool = False,
        attendance_cap: int = 10
    ) -> Dict[str, Any]:
        """
        Classify an activity and determine its risk profile
        """
        if equipment is None:
            equipment = []

        # Get space risk profile
        space_profile = db.query(SpaceRiskProfile).filter(
            SpaceRiskProfile.space_id == space_id
        ).first()

        if not space_profile:
            raise ClassificationError(f"Space profile {space_id} not found")

        # Determine base activity class slug
        activity_class_slug = ActivityClassificationEngine._determine_base_class_slug(declared_activity)

        # Get the actual activity class from the database
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.slug == activity_class_slug
        ).first()

        if not activity_class:
            # If the specific class doesn't exist in DB, use the closest match
            activity_class = ActivityClassificationEngine._find_closest_class_in_db(db, activity_class_slug)
            if not activity_class:
                # Fallback to passive class if nothing matches
                activity_class = db.query(ActivityClass).filter(ActivityClass.slug == 'passive').first()
                if not activity_class:
                    raise ClassificationError("No activity classes defined in the system")

        # Calculate risk modifiers
        risk_modifiers = ActivityClassificationEngine._calculate_risk_modifiers(
            float(activity_class.base_risk_score) if activity_class.base_risk_score else 0.1,
            space_profile,
            equipment,
            alcohol,
            minors_present,
            attendance_cap
        )

        # Calculate final risk score
        base_risk = float(activity_class.base_risk_score) if activity_class.base_risk_score else 0.1
        final_risk_score = ActivityClassificationEngine._apply_modifiers(
            base_risk,
            risk_modifiers
        )

        # Find appropriate activity class based on risk level
        matched_class = ActivityClassificationEngine._find_matching_class(
            db, final_risk_score, alcohol, minors_present
        )

        if not matched_class:
            return {
                'activity_class': None,
                'risk_score': final_risk_score,
                'required_limits': {},
                'prohibited': True,
                'violation_reasons': ['No matching activity class found for calculated risk']
            }

        # Validate against class restrictions
        violations = ActivityClassificationEngine._validate_against_class(
            matched_class, alcohol, minors_present, equipment
        )

        return {
            'activity_class_id': matched_class.id,
            'activity_class_slug': matched_class.slug,
            'risk_score': round(final_risk_score, 2),
            'required_limits': matched_class.default_limits or {},
            'prohibited': len(violations) > 0,
            'violation_reasons': violations
        }

    @staticmethod
    def _determine_base_class_slug(declared_activity: str) -> str:
        """
        Determine the base activity class slug based on declared activity
        """
        activity_lower = declared_activity.lower()

        # Define activity patterns
        activity_patterns = {
            'passive': [
                'board games', 'card games', 'chess', 'checkers', 'scrabble',
                'reading', 'book club', 'discussion', 'philosophy', 'language exchange',
                'movie night', 'silent study', 'writing', 'knitting', 'sewing',
                'painting', 'drawing', 'crafting', 'storytelling', 'silent reading'
            ],
            'light_physical': [
                'yoga', 'dance', 'stretching', 'exercise', 'fitness',
                'cooking', 'baking', 'mixology', 'bartending',
                'arts and crafts', 'pottery', 'ceramics',
                'photography', 'filmmaking', 'music', 'singing'
            ],
            'tool_based': [
                'repair', 'fixing', 'woodworking', 'carpentry', 'metalworking',
                'electronics', 'soldering', 'welding', 'machining',
                'bike repair', 'car maintenance', 'gardening tools',
                'power tools', 'drill', 'saw', 'grinder', 'lathe'
            ]
        }

        # Match against patterns
        for class_name, patterns in activity_patterns.items():
            for pattern in patterns:
                if pattern in activity_lower:
                    return class_name

        # Default to passive if no match found
        return 'passive'

    @staticmethod
    def _find_closest_class_in_db(db: Session, suggested_slug: str) -> Optional[ActivityClass]:
        """
        Find the closest matching activity class in the database
        """
        # First try exact match
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.slug == suggested_slug
        ).first()
        
        if activity_class:
            return activity_class
        
        # If not found, try to find similar classes
        if 'passive' in suggested_slug or suggested_slug in ['board games', 'reading', 'discussion']:
            return db.query(ActivityClass).filter(ActivityClass.slug == 'passive').first()
        elif 'physical' in suggested_slug or suggested_slug in ['yoga', 'dance', 'cooking']:
            return db.query(ActivityClass).filter(ActivityClass.slug == 'light_physical').first()
        elif 'tool' in suggested_slug or suggested_slug in ['repair', 'woodworking']:
            return db.query(ActivityClass).filter(ActivityClass.slug == 'tool_based').first()
        
        return None

    @staticmethod
    def _calculate_risk_modifiers(
        base_risk: float,
        space_profile: SpaceRiskProfile,
        equipment: list,
        alcohol: bool,
        minors_present: bool,
        attendance_cap: int
    ) -> Dict[str, float]:
        """
        Calculate risk modifiers based on various factors
        """
        modifiers = {}

        # Space hazard modifier
        if space_profile.hazard_rating is not None:
            modifiers['space_hazard'] = float(space_profile.hazard_rating)

        # Equipment risk modifier
        equipment_risk = 1.0
        for equip in equipment:
            if equip in ActivityClassificationEngine.EQUIPMENT_RISK_MULTIPLIERS:
                equipment_risk *= ActivityClassificationEngine.EQUIPMENT_RISK_MULTIPLIERS[equip]
        modifiers['equipment'] = equipment_risk

        # Alcohol modifier
        if alcohol:
            modifiers['alcohol'] = 1.4

        # Minors modifier
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
        Apply risk modifiers to base risk score
        """
        final_risk = base_risk

        for modifier_name, modifier_value in modifiers.items():
            if modifier_name == 'space_hazard':
                # Space hazard adds to risk rather than multiplying
                final_risk = min(1.0, final_risk + (modifier_value / 10.0))
            else:
                # Other modifiers multiply the risk
                final_risk = min(1.0, final_risk * modifier_value)

        return final_risk

    @staticmethod
    def _find_matching_class(
        db: Session,
        risk_score: float,
        alcohol: bool,
        minors_present: bool
    ) -> Optional[ActivityClass]:
        """
        Find the most appropriate activity class based on risk score
        """
        # Query all activity classes ordered by risk threshold
        classes = db.query(ActivityClass).order_by(ActivityClass.base_risk_score).all()

        # Find the first class that accommodates the risk level and constraints
        for cls in classes:
            # Check if risk score fits within class range (with some tolerance)
            threshold = float(cls.base_risk_score) + 0.3 if cls.base_risk_score is not None else 1.0
            if risk_score <= threshold:  # Allow some flexibility
                # Check alcohol and minors constraints
                if (not alcohol or cls.allows_alcohol) and (not minors_present or cls.allows_minors):
                    return cls

        # If no class fits the risk level, return the highest risk class that allows the constraints
        for cls in reversed(classes):
            if (not alcohol or cls.allows_alcohol) and (not minors_present or cls.allows_minors):
                return cls

        # Last resort: return any class that matches constraints, regardless of risk
        for cls in classes:
            if (not alcohol or cls.allows_alcohol) and (not minors_present or cls.allows_minors):
                return cls

        return None

    @staticmethod
    def _validate_against_class(
        activity_class: ActivityClass,
        alcohol: bool,
        minors_present: bool,
        equipment: list
    ) -> list:
        """
        Validate the activity against class restrictions
        """
        violations = []

        if alcohol and not activity_class.allows_alcohol:
            violations.append("Alcohol not permitted for this activity class")

        if minors_present and not activity_class.allows_minors:
            violations.append("Minors not permitted for this activity class")

        # Check prohibited equipment
        if activity_class.prohibited_equipment:
            for equip in equipment:
                if equip in activity_class.prohibited_equipment:
                    violations.append(f"Equipment '{equip}' prohibited for this activity class")

        return violations


class ActivityProfile:
    """
    Represents the output of activity classification
    """
    def __init__(
        self,
        activity_class_id: Optional[str],
        activity_class_slug: Optional[str],
        risk_score: float,
        required_limits: Dict[str, Any],
        prohibited: bool,
        violation_reasons: Optional[list] = None
    ):
        self.activity_class_id = activity_class_id
        self.activity_class_slug = activity_class_slug
        self.risk_score = risk_score
        self.required_limits = required_limits
        self.prohibited = prohibited
        self.violation_reasons = violation_reasons or []
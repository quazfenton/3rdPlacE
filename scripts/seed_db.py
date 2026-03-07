#!/usr/bin/env python3
"""
Database Seed Script for Third Place Platform

Seeds the database with:
- Default activity classes
- Sample policy roots
- Test users
- Sample spaces
- Sample insurance envelopes

Usage:
    python scripts/seed_db.py
    
    # Reset and reseed
    python scripts/seed_db.py --reset
    
    # Seed only specific data
    python scripts/seed_db.py --activity-classes --users
"""
import argparse
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.database import SessionLocal, engine, Base
from models.insurance_models import (
    ActivityClass, PolicyRoot, SpaceRiskProfile,
    InsuranceEnvelope, User
)
from services.auth_service import pwd_context


def reset_database():
    """Drop and recreate all tables"""
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Database reset complete")


def seed_activity_classes(db):
    """Seed default activity classes"""
    print("\nSeeding activity classes...")
    
    activity_classes = [
        ActivityClass(
            slug="passive",
            description="Low-risk passive activities like board games, reading, discussions, and social gatherings",
            base_risk_score=0.10,
            default_limits={"general_liability": 1000000, "property_damage": 500000},
            prohibited_equipment={},
            allows_alcohol=True,
            allows_minors=True
        ),
        ActivityClass(
            slug="light_physical",
            description="Light physical activities like yoga, dance, fitness classes, and cooking workshops",
            base_risk_score=0.35,
            default_limits={"general_liability": 1500000, "property_damage": 750000},
            prohibited_equipment={"power_tools": "Power tools not allowed"},
            allows_alcohol=True,
            allows_minors=True
        ),
        ActivityClass(
            slug="arts_crafts",
            description="Arts and crafts activities including painting, pottery, sewing, and crafting",
            base_risk_score=0.25,
            default_limits={"general_liability": 1250000, "property_damage": 600000},
            prohibited_equipment={
                "power_saws": "Power saws not allowed",
                "welding_equipment": "Welding not allowed"
            },
            allows_alcohol=True,
            allows_minors=True
        ),
        ActivityClass(
            slug="tool_based",
            description="Activities involving hand tools and light equipment like woodworking and repairs",
            base_risk_score=0.70,
            default_limits={"general_liability": 2000000, "property_damage": 1000000},
            prohibited_equipment={
                "industrial_machinery": "Industrial machinery not allowed",
                "explosives": "No explosives or fireworks"
            },
            allows_alcohol=False,
            allows_minors=False
        ),
        ActivityClass(
            slug="educational",
            description="Educational activities including lectures, workshops, seminars, and classes",
            base_risk_score=0.15,
            default_limits={"general_liability": 1000000, "property_damage": 500000},
            prohibited_equipment={},
            allows_alcohol=True,
            allows_minors=True
        ),
        ActivityClass(
            slug="music_performance",
            description="Music performances, rehearsals, and practice sessions",
            base_risk_score=0.20,
            default_limits={"general_liability": 1250000, "property_damage": 600000},
            prohibited_equipment={"pyrotechnics": "No pyrotechnics or flames"},
            allows_alcohol=True,
            allows_minors=True
        )
    ]
    
    for ac in activity_classes:
        existing = db.query(ActivityClass).filter(ActivityClass.slug == ac.slug).first()
        if not existing:
            db.add(ac)
            print(f"  Added activity class: {ac.slug}")
        else:
            print(f"  Skipped (exists): {ac.slug}")
    
    db.commit()
    print(f"Seeded {len(activity_classes)} activity classes")


def seed_policy_roots(db):
    """Seed default policy roots"""
    print("\nSeeding policy roots...")
    
    now = datetime.now(timezone.utc)
    
    policies = [
        PolicyRoot(
            insurer_name="Third Place Insurance Co.",
            policy_number="TPL-2026-001",
            jurisdiction="US-CA",
            effective_from=now - timedelta(days=30),
            effective_until=now + timedelta(days=335),
            activity_classes={
                "passive": {"multiplier": 1.0},
                "light_physical": {"multiplier": 1.5},
                "arts_crafts": {"multiplier": 1.25},
                "tool_based": {"multiplier": 2.5},
                "educational": {"multiplier": 1.0},
                "music_performance": {"multiplier": 1.2}
            },
            base_limits={"general_liability": 1000000, "property_damage": 500000},
            exclusions={
                "intentional_acts": "Intentional damage or injury not covered",
                "professional_services": "Professional services not covered",
                "automotive": "Vehicle-related incidents not covered"
            },
            status="active"
        ),
        PolicyRoot(
            insurer_name="Third Place Insurance Co.",
            policy_number="TPL-2026-002",
            jurisdiction="US-NY",
            effective_from=now - timedelta(days=30),
            effective_until=now + timedelta(days=335),
            activity_classes={
                "passive": {"multiplier": 1.1},
                "light_physical": {"multiplier": 1.6},
                "arts_crafts": {"multiplier": 1.3},
                "tool_based": {"multiplier": 2.7},
                "educational": {"multiplier": 1.1},
                "music_performance": {"multiplier": 1.3}
            },
            base_limits={"general_liability": 1250000, "property_damage": 600000},
            exclusions={
                "intentional_acts": "Intentional damage or injury not covered",
                "professional_services": "Professional services not covered"
            },
            status="active"
        )
    ]
    
    for policy in policies:
        existing = db.query(PolicyRoot).filter(
            PolicyRoot.policy_number == policy.policy_number
        ).first()
        if not existing:
            db.add(policy)
            print(f"  Added policy: {policy.policy_number}")
        else:
            print(f"  Skipped (exists): {policy.policy_number}")
    
    db.commit()
    print(f"Seeded {len(policies)} policy roots")


def seed_users(db):
    """Seed test users"""
    print("\nSeeding users...")
    
    users = [
        User(
            username="admin",
            email="admin@thirdplace.io",
            hashed_password=pwd_context.hash("Admin123!"),
            role="admin",
            disabled=False
        ),
        User(
            username="platform_operator",
            email="operator@thirdplace.io",
            hashed_password=pwd_context.hash("Operator123!"),
            role="platform_operator",
            disabled=False
        ),
        User(
            username="space_owner",
            email="owner@thirdplace.io",
            hashed_password=pwd_context.hash("Owner123!"),
            role="space_owner",
            disabled=False
        ),
        User(
            username="steward",
            email="steward@thirdplace.io",
            hashed_password=pwd_context.hash("Steward123!"),
            role="steward",
            disabled=False
        ),
        User(
            username="participant",
            email="participant@thirdplace.io",
            hashed_password=pwd_context.hash("Participant123!"),
            role="participant",
            disabled=False
        ),
        User(
            username="testuser",
            email="test@example.com",
            hashed_password=pwd_context.hash("Test123!"),
            role="space_owner",
            disabled=False
        )
    ]
    
    for user in users:
        existing = db.query(User).filter(User.username == user.username).first()
        if not existing:
            db.add(user)
            print(f"  Added user: {user.username} ({user.role})")
        else:
            print(f"  Skipped (exists): {user.username}")
    
    db.commit()
    print(f"Seeded {len(users)} users")
    
    print("\n  ⚠️  Test User Credentials:")
    print("     admin / Admin123!")
    print("     platform_operator / Operator123!")
    print("     space_owner / Owner123!")
    print("     steward / Steward123!")
    print("     participant / Participant123!")
    print("     testuser / Test123!")


def seed_spaces(db):
    """Seed sample spaces"""
    print("\nSeeding spaces...")
    
    spaces = [
        SpaceRiskProfile(
            space_id="test-space-001",
            owner_id="test-owner",
            name="Community Center Main Hall",
            hazard_rating=0.20,
            floor_type="hardwood",
            stairs=False,
            tools_present=False,
            fire_suppression=True,
            prior_claims=0,
            restrictions={"max_capacity": 100, "quiet_hours": "22:00-08:00"}
        ),
        SpaceRiskProfile(
            space_id="test-space-002",
            owner_id="test-owner",
            name="Workshop Space",
            hazard_rating=0.50,
            floor_type="concrete",
            stairs=False,
            tools_present=True,
            fire_suppression=True,
            prior_claims=0,
            restrictions={"max_capacity": 30, "safety_equipment_required": True}
        ),
        SpaceRiskProfile(
            space_id="test-space-003",
            owner_id="test-owner",
            name="Yoga Studio",
            hazard_rating=0.10,
            floor_type="cork",
            stairs=False,
            tools_present=False,
            fire_suppression=True,
            prior_claims=0,
            restrictions={"max_capacity": 25, "shoes_off": True}
        )
    ]
    
    for space in spaces:
        existing = db.query(SpaceRiskProfile).filter(
            SpaceRiskProfile.space_id == space.space_id
        ).first()
        if not existing:
            db.add(space)
            print(f"  Added space: {space.name}")
        else:
            print(f"  Skipped (exists): {space.name}")
    
    db.commit()
    print(f"Seeded {len(spaces)} spaces")


def seed_sample_envelopes(db):
    """Seed sample insurance envelopes"""
    print("\nSeeding sample envelopes...")
    
    # Get required data
    policy = db.query(PolicyRoot).first()
    activity_class = db.query(ActivityClass).filter(ActivityClass.slug == "passive").first()
    space = db.query(SpaceRiskProfile).first()
    
    if not all([policy, activity_class, space]):
        print("  Skipping envelopes (missing required data)")
        return
    
    now = datetime.now(timezone.utc)
    
    envelopes = [
        InsuranceEnvelope(
            policy_root_id=policy.id,
            activity_class_id=activity_class.id,
            space_id=space.space_id,
            steward_id="test-steward",
            platform_entity_id="platform-001",
            event_metadata={"event_name": "Board Game Night", "organizer": "Local Gaming Club"},
            attendance_cap=30,
            duration_minutes=180,
            alcohol=False,
            minors_present=True,
            coverage_limits={"general_liability": 1000000},
            jurisdiction=policy.jurisdiction,
            valid_from=now + timedelta(days=1),
            valid_until=now + timedelta(days=1, hours=3),
            status="active",
            certificate_url="/api/v1/certificates/sample-001.pdf"
        ),
        InsuranceEnvelope(
            policy_root_id=policy.id,
            activity_class_id=activity_class.id,
            space_id=space.space_id,
            steward_id="test-steward",
            platform_entity_id="platform-001",
            event_metadata={"event_name": "Book Club Meeting", "organizer": "City Library"},
            attendance_cap=20,
            duration_minutes=120,
            alcohol=False,
            minors_present=False,
            coverage_limits={"general_liability": 1000000},
            jurisdiction=policy.jurisdiction,
            valid_from=now + timedelta(days=2),
            valid_until=now + timedelta(days=2, hours=2),
            status="pending"
        ),
        InsuranceEnvelope(
            policy_root_id=policy.id,
            activity_class_id=db.query(ActivityClass).filter(ActivityClass.slug == "light_physical").first().id,
            space_id=db.query(SpaceRiskProfile).filter(SpaceRiskProfile.space_id == "test-space-003").first().space_id,
            steward_id="test-steward",
            platform_entity_id="platform-001",
            event_metadata={"event_name": "Morning Yoga Class", "instructor": "Jane Doe"},
            attendance_cap=25,
            duration_minutes=60,
            alcohol=False,
            minors_present=True,
            coverage_limits={"general_liability": 1500000},
            jurisdiction=policy.jurisdiction,
            valid_from=now - timedelta(hours=1),
            valid_until=now + timedelta(hours=1),
            status="active"
        )
    ]
    
    for envelope in envelopes:
        db.add(envelope)
    
    db.commit()
    print(f"Seeded {len(envelopes)} sample envelopes")


def main():
    parser = argparse.ArgumentParser(description="Seed database with sample data")
    parser.add_argument("--reset", action="store_true", help="Reset database before seeding")
    parser.add_argument("--activity-classes", action="store_true", help="Seed activity classes only")
    parser.add_argument("--policies", action="store_true", help="Seed policy roots only")
    parser.add_argument("--users", action="store_true", help="Seed users only")
    parser.add_argument("--spaces", action="store_true", help="Seed spaces only")
    parser.add_argument("--envelopes", action="store_true", help="Seed envelopes only")
    parser.add_argument("--all", action="store_true", help="Seed all data (default)")
    
    args = parser.parse_args()
    
    # If no specific seed option, seed all
    seed_all = not any([
        args.activity_classes, args.policies, args.users,
        args.spaces, args.envelopes
    ]) or args.all
    
    db = SessionLocal()
    
    try:
        if args.reset:
            reset_database()
        else:
            # Create tables if they don't exist
            Base.metadata.create_all(bind=engine)
        
        print("\n" + "=" * 60)
        print("Third Place Platform - Database Seed")
        print("=" * 60)
        
        if seed_all or args.activity_classes:
            seed_activity_classes(db)
        
        if seed_all or args.policies:
            seed_policy_roots(db)
        
        if seed_all or args.users:
            seed_users(db)
        
        if seed_all or args.spaces:
            seed_spaces(db)
        
        if seed_all or args.envelopes:
            seed_sample_envelopes(db)
        
        print("\n" + "=" * 60)
        print("Database seed complete!")
        print("=" * 60)
        
    except Exception as e:
        db.rollback()
        print(f"\n❌ Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

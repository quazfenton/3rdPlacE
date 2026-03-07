#!/usr/bin/env python3
"""
Initialization script for Third Place Platform

Creates database tables and seeds initial data.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config.database import Base, DATABASE_URL
from models.insurance_models import (
    PolicyRoot, ActivityClass, SpaceRiskProfile,
    AuditLog, User, RefreshToken
)


def init_db(seed_data: bool = True):
    """
    Initialize the database with required tables and optional seed data.
    
    Args:
        seed_data: If True, creates default seed data for development
    """
    print(f"Initializing database with URL: {DATABASE_URL}")
    
    # Create engine and tables
    engine = create_engine(DATABASE_URL)
    
    # Create all tables
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")
    
    if not seed_data:
        print("Skipping seed data (seed_data=False)")
        return
    
    # Create session
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        # Check if we already have seed data
        existing_policy = db.query(PolicyRoot).first()
        existing_activity = db.query(ActivityClass).first()
        
        if existing_policy or existing_activity:
            print("Seed data already exists. Skipping seed data creation.")
            print(f"  - Policies: {db.query(PolicyRoot).count()}")
            print(f"  - Activity Classes: {db.query(ActivityClass).count()}")
            print(f"  - Spaces: {db.query(SpaceRiskProfile).count()}")
            return

        print("Creating seed data...")
        
        # Create default policy root
        now = datetime.now(timezone.utc)
        default_policy = PolicyRoot(
            insurer_name="Third Place Insurance",
            policy_number="TP-DEFAULT-001",
            jurisdiction="US-DEFAULT",
            effective_from=now,
            effective_until=now + timedelta(days=365),
            activity_classes={
                "passive": {"limits": {"general_liability": 1000000}},
                "light_physical": {"limits": {"general_liability": 1500000}},
                "tool_based": {"limits": {"general_liability": 2000000}}
            },
            base_limits={"general_liability": 1000000},
            exclusions={
                "general": [
                    "Intentional acts",
                    "Criminal activities",
                    "Nuclear hazards",
                    "War and terrorism"
                ],
                "property": [
                    "Damage to rented premises",
                    "Electronic data loss"
                ]
            },
            status="active"
        )
        db.add(default_policy)
        print("  - Created default policy root")

        # Create default activity classes
        activity_classes = [
            ActivityClass(
                slug="passive",
                description="Passive activities like board games, reading, discussion groups, book clubs",
                base_risk_score=0.10,
                default_limits={"general_liability": 1000000, "medical_payments": 5000},
                prohibited_equipment={},
                allows_alcohol=True,
                allows_minors=True
            ),
            ActivityClass(
                slug="light_physical",
                description="Light physical activities like yoga, dance, cooking classes, fitness",
                base_risk_score=0.35,
                default_limits={"general_liability": 1500000, "medical_payments": 10000},
                prohibited_equipment={
                    "power_tools": "Power tools not permitted",
                    "welding": "Welding equipment not permitted"
                },
                allows_alcohol=True,
                allows_minors=True
            ),
            ActivityClass(
                slug="tool_based",
                description="Activities involving tools like woodworking, repairs, metalworking",
                base_risk_score=0.70,
                default_limits={"general_liability": 2000000, "medical_payments": 15000},
                prohibited_equipment={
                    "explosives": "Explosives not permitted",
                    "hazardous_chemicals": "Hazardous chemicals not permitted"
                },
                allows_alcohol=False,
                allows_minors=False
            )
        ]
        for ac in activity_classes:
            db.add(ac)
        print("  - Created 3 activity classes")

        # Create sample space risk profiles
        sample_spaces = [
            SpaceRiskProfile(
                owner_id="seed-owner-001",
                name="Community Center Room A",
                hazard_rating=0.15,
                floor_type="hardwood",
                stairs=False,
                tools_present=False,
                fire_suppression=True,
                prior_claims=0,
                restrictions={"max_noise_level": "moderate", "quiet_hours": "22:00-08:00"}
            ),
            SpaceRiskProfile(
                owner_id="seed-owner-001",
                name="Maker Space",
                hazard_rating=0.45,
                floor_type="concrete",
                stairs=False,
                tools_present=True,
                fire_suppression=True,
                prior_claims=0,
                restrictions={"safety_equipment_required": True, "supervision_required": True}
            ),
            SpaceRiskProfile(
                owner_id="seed-owner-002",
                name="Yoga Studio",
                hazard_rating=0.10,
                floor_type="cork",
                stairs=False,
                tools_present=False,
                fire_suppression=True,
                prior_claims=0,
                restrictions={"shoes_off": True, "max_capacity": 30}
            )
        ]
        for space in sample_spaces:
            db.add(space)
        print("  - Created 3 sample spaces")

        # Create default admin user
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        admin_user = User(
            username="admin",
            email="admin@thirdplace.local",
            hashed_password=pwd_context.hash("Admin123!ChangeMe"),
            role="admin",
            disabled=False
        )
        db.add(admin_user)
        print("  - Created admin user (username: admin, password: Admin123!ChangeMe)")

        # Create sample steward user
        steward_user = User(
            username="steward_demo",
            email="steward@thirdplace.local",
            hashed_password=pwd_context.hash("Steward123!ChangeMe"),
            role="steward",
            disabled=False
        )
        db.add(steward_user)
        print("  - Created steward user (username: steward_demo)")

        # Create sample space owner user
        owner_user = User(
            username="space_owner_demo",
            email="owner@thirdplace.local",
            hashed_password=pwd_context.hash("Owner123!ChangeMe"),
            role="space_owner",
            disabled=False
        )
        db.add(owner_user)
        print("  - Created space owner user (username: space_owner_demo)")

        # Commit all changes
        db.commit()
        print("\nDatabase initialized successfully!")
        print("\n⚠️  IMPORTANT: Change default passwords in production!")
        print("\nDefault credentials:")
        print("  Admin: admin / Admin123!ChangeMe")
        print("  Steward: steward_demo / Steward123!ChangeMe")
        print("  Space Owner: space_owner_demo / Owner123!ChangeMe")

    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


def clean_db():
    """
    Drop all tables from the database.
    WARNING: This will delete all data!
    """
    print("WARNING: This will delete ALL data from the database!")
    confirm = input("Type 'DELETE' to confirm: ")
    
    if confirm != "DELETE":
        print("Aborted.")
        return
    
    engine = create_engine(DATABASE_URL)
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("All tables dropped.")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialize Third Place Platform database")
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Create tables only, without seed data"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Drop all tables (WARNING: deletes all data)"
    )
    
    args = parser.parse_args()
    
    if args.clean:
        clean_db()
    else:
        init_db(seed_data=not args.no_seed)

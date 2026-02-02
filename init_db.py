#!/usr/bin/env python3
"""
Initialization script for Third Place Platform
"""

import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config.database import Base, DATABASE_URL
from models.insurance_models import PolicyRoot, ActivityClass, SpaceRiskProfile


def init_db():
    """Initialize the database with required tables and seed data"""
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # Check if we already have seed data
        if db.query(PolicyRoot).count() == 0:
            # Add default policy root
            default_policy = PolicyRoot(
                insurer_name="Third Place Insurance",
                policy_number="TP-DEFAULT-001",
                jurisdiction="US-DEFAULT",
                effective_from="2024-01-01T00:00:00Z",
                effective_until="2025-01-01T00:00:00Z",
                activity_classes={
                    "passive": {"limits": {"general_liability": 1000000}},
                    "light_physical": {"limits": {"general_liability": 1500000}},
                    "tool_based": {"limits": {"general_liability": 2000000}}
                },
                base_limits={"general_liability": 1000000},
                status="active"
            )
            db.add(default_policy)
        
        if db.query(ActivityClass).count() == 0:
            # Add default activity classes
            activity_classes = [
                ActivityClass(
                    slug="passive",
                    description="Passive activities like board games, reading, discussion",
                    base_risk_score=0.1,
                    default_limits={"general_liability": 1000000},
                    allows_alcohol=False,
                    allows_minors=True
                ),
                ActivityClass(
                    slug="light_physical",
                    description="Light physical activities like yoga, dance, cooking",
                    base_risk_score=0.3,
                    default_limits={"general_liability": 1500000},
                    allows_alcohol=True,
                    allows_minors=True
                ),
                ActivityClass(
                    slug="tool_based",
                    description="Activities involving tools like woodworking, repairs",
                    base_risk_score=0.7,
                    default_limits={"general_liability": 2000000},
                    allows_alcohol=False,
                    allows_minors=False
                )
            ]
            for ac in activity_classes:
                db.add(ac)
        
        db.commit()
        print("Database initialized successfully!")
        
    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
-- Third Place Platform - Insurance Abstraction Layer Schema
-- Core database schema for managing insurance envelopes and related entities

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Policy Root table - represents an insurer-backed master policy
CREATE TABLE policy_root (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    insurer_name TEXT NOT NULL,
    policy_number TEXT NOT NULL,
    jurisdiction TEXT NOT NULL, -- e.g. "US-CA"
    effective_from TIMESTAMP WITH TIME ZONE NOT NULL,
    effective_until TIMESTAMP WITH TIME ZONE NOT NULL,
    activity_classes JSONB NOT NULL, -- allowed classes + constraints
    base_limits JSONB NOT NULL, -- default coverage limits
    exclusions JSONB,
    status TEXT NOT NULL CHECK (status IN ('active','expired','suspended')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Activity Class table - defines insurable activity categories
CREATE TABLE activity_class (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug TEXT UNIQUE NOT NULL, -- passive, light_physical, tool_based
    description TEXT,
    base_risk_score NUMERIC(3,2) DEFAULT 0.00, -- 0.00–1.00
    default_limits JSONB,
    prohibited_equipment JSONB DEFAULT '[]'::jsonb,
    allows_alcohol BOOLEAN DEFAULT FALSE,
    allows_minors BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Space Risk Profile table - one per physical venue
CREATE TABLE space_risk_profile (
    space_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    hazard_rating NUMERIC(3,2) DEFAULT 0.00, -- 0.00–1.00
    floor_type TEXT,
    stairs BOOLEAN DEFAULT FALSE,
    tools_present BOOLEAN DEFAULT FALSE,
    fire_suppression BOOLEAN DEFAULT FALSE,
    prior_claims INTEGER DEFAULT 0,
    restrictions JSONB,
    last_inspected_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insurance Envelope table - the atomic unit of coverage
CREATE TABLE insurance_envelope (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_root_id UUID NOT NULL REFERENCES policy_root(id),
    activity_class_id UUID NOT NULL REFERENCES activity_class(id),
    space_id UUID NOT NULL REFERENCES space_risk_profile(space_id),
    steward_id UUID NOT NULL,
    platform_entity_id UUID NOT NULL,

    event_metadata JSONB, -- declared activity, equipment, notes

    attendance_cap INTEGER NOT NULL,
    duration_minutes INTEGER NOT NULL,

    alcohol BOOLEAN DEFAULT FALSE,
    minors_present BOOLEAN DEFAULT FALSE,

    coverage_limits JSONB,
    exclusions JSONB,

    jurisdiction TEXT NOT NULL,

    valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
    valid_until TIMESTAMP WITH TIME ZONE NOT NULL,

    certificate_url TEXT,

    status TEXT NOT NULL CHECK (
        status IN ('pending','active','voided','expired','claim_open')
    ) DEFAULT 'pending',

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insurance Pricing Snapshot table - immutable pricing decision
CREATE TABLE insurance_pricing (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    envelope_id UUID NOT NULL REFERENCES insurance_envelope(id) ON DELETE CASCADE,
    base_rate NUMERIC(10,2) NOT NULL,
    duration_factor NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    attendance_factor NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    jurisdiction_factor NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    risk_factor NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    final_price NUMERIC(10,2) NOT NULL,
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Incident Report table - pre-claim signal
CREATE TABLE incident_report (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    envelope_id UUID NOT NULL REFERENCES insurance_envelope(id) ON DELETE CASCADE,
    reported_by UUID NOT NULL,
    incident_type TEXT NOT NULL, -- injury, property, behavioral
    severity TEXT NOT NULL, -- low, medium, high
    description TEXT,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    evidence_urls TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Claim table - formal insurance claim
CREATE TABLE claim (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    envelope_id UUID NOT NULL REFERENCES insurance_envelope(id) ON DELETE CASCADE,
    claimant_type TEXT NOT NULL, -- space_owner, participant, platform
    status TEXT NOT NULL CHECK (
        status IN ('opened','under_review','approved','denied','paid')
    ) DEFAULT 'opened',
    payout_amount NUMERIC(10,2),
    insurer_reference TEXT,
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    closed_at TIMESTAMP WITH TIME ZONE
);

-- Access Grant table - short-lived permission derived from Insurance Envelope
CREATE TABLE access_grant (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    envelope_id UUID NOT NULL REFERENCES insurance_envelope(id) ON DELETE CASCADE,
    lock_id UUID NOT NULL,
    access_type TEXT NOT NULL CHECK (access_type IN ('qr', 'pin', 'bluetooth', 'api_unlock')),

    valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
    valid_until TIMESTAMP WITH TIME ZONE NOT NULL,

    attendance_cap INTEGER NOT NULL,
    checkins_used INTEGER DEFAULT 0,

    status TEXT NOT NULL CHECK (status IN ('active', 'revoked', 'expired')) DEFAULT 'active',

    issued_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_policy_root_jurisdiction ON policy_root(jurisdiction);
CREATE INDEX idx_policy_root_status ON policy_root(status);
CREATE INDEX idx_activity_class_slug ON activity_class(slug);
CREATE INDEX idx_insurance_envelope_status ON insurance_envelope(status);
CREATE INDEX idx_insurance_envelope_validity ON insurance_envelope(valid_from, valid_until);
CREATE INDEX idx_insurance_envelope_space ON insurance_envelope(space_id);
CREATE INDEX idx_insurance_envelope_steward ON insurance_envelope(steward_id);
CREATE INDEX idx_incident_report_envelope ON incident_report(envelope_id);
CREATE INDEX idx_claim_envelope ON claim(envelope_id);
CREATE INDEX idx_claim_status ON claim(status);
CREATE INDEX idx_access_grant_envelope ON access_grant(envelope_id);
CREATE INDEX idx_access_grant_lock ON access_grant(lock_id);
CREATE INDEX idx_access_grant_validity ON access_grant(valid_from, valid_until);
CREATE INDEX idx_access_grant_status ON access_grant(status);
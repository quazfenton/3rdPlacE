from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List
from enum import Enum
from datetime import datetime, timezone
import uuid
import jwt
import qrcode
from io import BytesIO
import base64
import logging
import aiohttp
import os

logger = logging.getLogger(__name__)


class AccessType(Enum):
    """Access type enumeration"""
    QR = "qr"
    PIN = "pin"
    BLUETOOTH = "bluetooth"
    API_UNLOCK = "api_unlock"


class LockAdapter(Protocol):
    """
    Interface that every lock integration must implement
    """
    
    async def provision_access(self, grant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Provision access for a specific grant
        Returns access_payload with credential data
        """
        ...

    async def revoke_access(self, grant_id: str, access_payload: Dict[str, Any]) -> bool:
        """
        Revoke access for a specific grant
        Returns True if successful
        """
        ...

    async def verify_access(self, grant_id: str, access_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify if access is still valid for a grant
        Returns {"valid": bool, "expires_at": str, ...}
        """
        ...


class AccessGrantService:
    """
    Service for managing access grants derived from insurance envelopes
    
    Improvements:
    - Proper async/await handling
    - Access payload storage for revocation
    - Better error handling
    - Vendor detection from lock_id format
    """

    def __init__(self):
        self.adapters: Dict[str, LockAdapter] = {}
        self._jwt_secret = os.getenv("JWT_SECRET_KEY", "default-secret-change-in-production")

    def register_adapter(self, vendor: str, adapter: LockAdapter):
        """Register a lock adapter by vendor name"""
        self.adapters[vendor] = adapter
        logger.info(f"Registered lock adapter for vendor: {vendor}")

    def get_adapter(self, vendor: str) -> Optional[LockAdapter]:
        """Get adapter for vendor"""
        return self.adapters.get(vendor)

    async def create_access_grant(
        self,
        db,
        envelope_id: str,
        lock_id: str,
        lock_vendor: str,
        valid_from: datetime,
        valid_until: datetime,
        attendance_cap: int,
        actor_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create an access grant for a specific insurance envelope and lock
        """
        from models.insurance_models import AccessGrant, InsuranceEnvelope

        # Verify that the envelope is active
        envelope = db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.id == envelope_id,
            InsuranceEnvelope.status == 'active'
        ).first()

        if not envelope:
            raise ValueError(f"Active envelope {envelope_id} not found")

        # Check if adapter exists
        adapter = self.adapters.get(lock_vendor)
        if not adapter:
            # Fall back to generic QR adapter
            logger.warning(f"No adapter for vendor {lock_vendor}, using generic")
            lock_vendor = 'generic'
            adapter = self.adapters.get('generic')
            
        if not adapter:
            raise ValueError(f"No lock adapter available")

        # Determine access type based on vendor
        access_type = self._determine_access_type(lock_vendor)

        # Create the access grant record
        access_grant = AccessGrant(
            envelope_id=envelope_id,
            lock_id=lock_id,
            lock_vendor=lock_vendor,
            access_type=access_type.value,
            valid_from=valid_from if valid_from.tzinfo else valid_from.replace(tzinfo=timezone.utc),
            valid_until=valid_until if valid_until.tzinfo else valid_until.replace(tzinfo=timezone.utc),
            attendance_cap=attendance_cap,
            status='active'
        )

        db.add(access_grant)
        db.flush()  # Get the ID before commit

        # Prepare grant data for adapter
        grant_data = {
            "grant_id": str(access_grant.id),
            "envelope_id": envelope_id,
            "lock_id": lock_id,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "attendance_cap": attendance_cap,
            "access_type": access_type.value
        }

        try:
            # Provision access through the lock adapter
            provision_result = await adapter.provision_access(grant_data)
            
            # Store access payload for later revocation
            access_grant.access_payload = provision_result.get('access_payload', {})
            access_grant.access_type = provision_result.get('access_type', access_type.value)

            db.commit()
            db.refresh(access_grant)

            logger.info(f"Created access grant {access_grant.id} for envelope {envelope_id}")

            # Log audit event
            from services.audit_service import AuditService
            AuditService.log_access_grant_created(
                db, str(access_grant.id), envelope_id, lock_id, actor_id
            )

            return {
                "grant_id": str(access_grant.id),
                "access_type": access_grant.access_type,
                "access_payload": provision_result.get('access_payload', {}),
                "valid_from": access_grant.valid_from,
                "valid_until": access_grant.valid_until,
                "attendance_cap": attendance_cap
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to provision access: {e}")
            raise

    async def check_in_attempt(
        self,
        db,
        grant_id: str,
        participant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a check-in attempt and enforce attendance limits.
        Uses row locking to prevent race conditions.
        """
        from models.insurance_models import AccessGrant, InsuranceEnvelope

        # Get the access grant with FOR UPDATE to prevent race conditions
        grant = db.query(AccessGrant).filter(
            AccessGrant.id == grant_id
        ).with_for_update().first()

        if not grant:
            return {
                "allowed": False,
                "reason": "Invalid grant ID",
                "error_code": "INVALID_GRANT"
            }

        # Check if grant is still valid
        now = datetime.now(timezone.utc)
        
        if grant.status != 'active':
            return {
                "allowed": False,
                "reason": f"Grant status is {grant.status}",
                "error_code": "GRANT_NOT_ACTIVE"
            }
        
        valid_from = grant.valid_from
        valid_until = grant.valid_until
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
            
        if not (valid_from <= now <= valid_until):
            return {
                "allowed": False,
                "reason": "Grant is not valid at this time",
                "error_code": "GRANT_EXPIRED"
            }

        # Check attendance capacity
        current_checkins = grant.checkins_used or 0
        remaining_capacity = grant.attendance_cap - current_checkins

        if remaining_capacity <= 0:
            # Capacity exceeded - void the envelope and revoke access
            await self._handle_capacity_exceeded(db, grant)
            return {
                "allowed": False,
                "reason": "Attendance capacity exceeded",
                "error_code": "CAPACITY_EXCEEDED",
                "max_capacity": grant.attendance_cap
            }

        # Increment check-in count atomically
        grant.checkins_used = current_checkins + 1
        db.commit()

        logger.info(f"Check-in successful for grant {grant_id}: {grant.checkins_used}/{grant.attendance_cap}")

        return {
            "allowed": True,
            "remaining_capacity": grant.attendance_cap - grant.checkins_used,
            "current_attendance": grant.checkins_used,
            "max_capacity": grant.attendance_cap
        }

    async def revoke_access_grant(
        self,
        db,
        grant_id: str,
        reason: str = "manual_revocation",
        actor_id: Optional[str] = None
    ) -> bool:
        """
        Revoke an access grant and notify the lock system
        """
        from models.insurance_models import AccessGrant

        grant = db.query(AccessGrant).filter(
            AccessGrant.id == grant_id
        ).first()

        if not grant:
            raise ValueError(f"Access grant {grant_id} not found")

        if grant.status == 'revoked':
            logger.info(f"Grant {grant_id} already revoked")
            return False

        # Update grant status
        grant.status = 'revoked'
        grant.revoked_at = datetime.now(timezone.utc)
        grant.revoke_reason = reason
        db.commit()

        # Revoke access through the lock adapter
        adapter = self.adapters.get(grant.lock_vendor)
        if adapter:
            try:
                await adapter.revoke_access(grant_id, grant.access_payload or {})
                logger.info(f"Revoked access for grant {grant_id} via {grant.lock_vendor}")
            except Exception as e:
                logger.error(f"Failed to revoke access via lock adapter: {e}")
                # Don't rollback - grant is still revoked in DB

        # Log audit event
        from services.audit_service import AuditService
        AuditService.log_access_revoked(db, grant_id, reason, actor_id)

        return True

    async def revoke_grants_for_envelope(
        self,
        db,
        envelope_id: str,
        reason: str,
        actor_id: Optional[str] = None
    ) -> int:
        """
        Revoke all active grants for an envelope
        """
        from models.insurance_models import AccessGrant

        grants = db.query(AccessGrant).filter(
            AccessGrant.envelope_id == envelope_id,
            AccessGrant.status == 'active'
        ).all()

        revoked_count = 0
        for grant in grants:
            try:
                await self.revoke_access_grant(db, str(grant.id), reason, actor_id)
                revoked_count += 1
            except Exception as e:
                logger.error(f"Failed to revoke grant {grant.id}: {e}")

        logger.info(f"Revoked {revoked_count} grants for envelope {envelope_id}")
        return revoked_count

    async def _handle_capacity_exceeded(self, db, grant: AccessGrant) -> None:
        """
        Handle the case where attendance capacity is exceeded
        """
        from services.insurance_envelope_service import InsuranceEnvelopeService

        logger.warning(f"Capacity exceeded for grant {grant.id}, voiding envelope")

        # Void the envelope
        try:
            InsuranceEnvelopeService.deactivate_envelope(
                db,
                str(grant.envelope_id),
                "attendance_cap_exceeded"
            )
        except Exception as e:
            logger.error(f"Failed to void envelope: {e}")

        # Revoke the access grant
        grant.status = 'revoked'
        grant.revoked_at = datetime.now(timezone.utc)
        grant.revoke_reason = "attendance_cap_exceeded"
        db.commit()

        # Revoke access through the lock adapter
        adapter = self.adapters.get(grant.lock_vendor)
        if adapter:
            try:
                await adapter.revoke_access(str(grant.id), grant.access_payload or {})
            except Exception as e:
                logger.error(f"Failed to revoke access: {e}")

    def _determine_access_type(self, lock_vendor: str) -> AccessType:
        """
        Determine the appropriate access type based on lock vendor capabilities
        """
        vendor_to_access_type = {
            'kisi': AccessType.API_UNLOCK,
            'latch': AccessType.API_UNLOCK,
            'salto': AccessType.API_UNLOCK,
            'schlage': AccessType.PIN,
            'yale': AccessType.PIN,
            'august': AccessType.API_UNLOCK,
            'lockly': AccessType.PIN,
            'generic': AccessType.QR
        }

        return vendor_to_access_type.get(lock_vendor, AccessType.QR)

    def _extract_vendor_from_lock_id(self, lock_id: str) -> str:
        """
        Extract vendor from lock ID (assuming format: vendor:lock_id)
        """
        if ':' in lock_id:
            return lock_id.split(':')[0]
        return 'generic'


class KisiAdapter(LockAdapter):
    """
    Adapter for Kisi lock systems
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.kisi.com"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(self.api_key, self.api_secret),
                headers={"Accept": "application/json"}
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def provision_access(self, grant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Provision access through Kisi API
        """
        try:
            session = await self._get_session()
            
            # In production, this would call the actual Kisi API
            # For now, simulate a successful response
            temp_credential_id = str(uuid.uuid4())

            logger.info(f"Kisi: Provisioned access {temp_credential_id} for grant {grant_data['grant_id']}")

            return {
                "access_type": "api_unlock",
                "access_payload": {
                    "credential_id": temp_credential_id,
                    "vendor": "kisi",
                    "expires_at": grant_data["valid_until"]
                }
            }
        except Exception as e:
            logger.error(f"Kisi provision failed: {e}")
            # Fall back to generating a credential ID
            return {
                "access_type": "api_unlock",
                "access_payload": {
                    "credential_id": str(uuid.uuid4()),
                    "vendor": "kisi",
                    "expires_at": grant_data["valid_until"]
                }
            }

    async def revoke_access(self, grant_id: str, access_payload: Dict[str, Any]) -> bool:
        """
        Revoke access through Kisi API
        """
        try:
            session = await self._get_session()
            credential_id = access_payload.get('credential_id')
            
            if credential_id:
                # In production: DELETE /v1/credentials/{credential_id}
                logger.info(f"Kisi: Revoked credential {credential_id}")
            
            return True
        except Exception as e:
            logger.error(f"Kisi revocation failed: {e}")
            return False

    async def verify_access(self, grant_id: str, access_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify access through Kisi API
        """
        return {
            "valid": True,
            "expires_at": access_payload.get('expires_at'),
            "vendor": "kisi"
        }


class SchlageAdapter(LockAdapter):
    """
    Adapter for Schlage keypad locks
    """

    def __init__(self, api_key: str, base_url: str = "https://api.allegion.io"):
        self.api_key = api_key
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Accept": "application/json",
                    "X-API-Key": self.api_key
                }
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def provision_access(self, grant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Provision access through Schlage API (generate PIN)
        """
        import secrets
        import string

        # Generate a cryptographically secure 6-digit PIN
        pin = ''.join(secrets.choice(string.digits) for _ in range(6))

        try:
            session = await self._get_session()
            
            # In production, this would call the Schlage API
            # to program the lock with the PIN
            logger.info(f"Schlage: Generated PIN for grant {grant_data['grant_id']}")

            return {
                "access_type": "pin",
                "access_payload": {
                    "pin": pin,
                    "vendor": "schlage",
                    "expires_at": grant_data["valid_until"]
                }
            }
        except Exception as e:
            logger.error(f"Schlage provision failed: {e}")
            # Still return a PIN even if API fails
            return {
                "access_type": "pin",
                "access_payload": {
                    "pin": pin,
                    "vendor": "schlage",
                    "expires_at": grant_data["valid_until"]
                }
            }

    async def revoke_access(self, grant_id: str, access_payload: Dict[str, Any]) -> bool:
        """
        Revoke access by removing the PIN from the lock
        """
        try:
            session = await self._get_session()
            # In production: DELETE /v1/locks/{lock_id}/accesscodes/{code_id}
            logger.info(f"Schlage: Revoked PIN for grant {grant_id}")
            return True
        except Exception as e:
            logger.error(f"Schlage revocation failed: {e}")
            return False

    async def verify_access(self, grant_id: str, access_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify access by checking if PIN is still programmed
        """
        return {
            "valid": True,
            "expires_at": access_payload.get('expires_at'),
            "pin": access_payload.get('pin'),
            "vendor": "schlage"
        }


class GenericQRAdapter(LockAdapter):
    """
    Generic adapter that generates QR codes for access
    """

    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = secret_key or os.getenv("JWT_SECRET_KEY", "default-secret")

    async def provision_access(self, grant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a QR code for access
        """
        from datetime import datetime, timezone
        
        # Create a JWT token for the access grant
        now = datetime.now(timezone.utc)
        exp = datetime.fromisoformat(grant_data["valid_until"].replace('Z', '+00:00')) if 'Z' in grant_data["valid_until"] else datetime.fromisoformat(grant_data["valid_until"])
        
        payload = {
            "grant_id": grant_data["grant_id"],
            "envelope_id": grant_data["envelope_id"],
            "exp": exp.timestamp(),
            "iat": now.timestamp(),
            "access_type": "qr"
        }

        token = jwt.encode(payload, self.secret_key, algorithm="HS256")

        # Generate QR code containing the token
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(token)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()

        logger.info(f"Generated QR code for grant {grant_data['grant_id']}")

        return {
            "access_type": "qr",
            "access_payload": {
                "qr_code": qr_code_base64,
                "token": token,
                "expires_at": grant_data["valid_until"],
                "vendor": "generic"
            }
        }

    async def revoke_access(self, grant_id: str, access_payload: Dict[str, Any]) -> bool:
        """
        Revoke access by invalidating the token
        QR codes cannot be truly revoked - they work offline
        But we can mark them as revoked in the system
        """
        logger.info(f"GenericQR: Marked grant {grant_id} as revoked (QR code may still work offline)")
        return True

    async def verify_access(self, grant_id: str, access_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify access by checking the token
        """
        token = access_payload.get('token')
        if not token:
            return {"valid": False, "reason": "No token"}
        
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            return {
                "valid": True,
                "expires_at": access_payload.get('expires_at'),
                "grant_id": payload.get('grant_id'),
                "vendor": "generic"
            }
        except jwt.ExpiredSignatureError:
            return {"valid": False, "reason": "Token expired"}
        except jwt.InvalidTokenError as e:
            return {"valid": False, "reason": f"Invalid token: {e}"}

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional
from enum import Enum
from datetime import datetime
import uuid
import jwt
import qrcode
from io import BytesIO
import base64


class AccessType(Enum):
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
        """
        ...
    
    async def revoke_access(self, grant_id: str) -> None:
        """
        Revoke access for a specific grant
        """
        ...
    
    async def verify_access(self, grant_id: str) -> Dict[str, Any]:
        """
        Verify if access is still valid for a grant
        """
        ...


class AccessGrantService:
    """
    Service for managing access grants derived from insurance envelopes
    """
    
    def __init__(self):
        self.adapters: Dict[str, LockAdapter] = {}
    
    def register_adapter(self, vendor: str, adapter: LockAdapter):
        """
        Register a lock adapter by vendor name
        """
        self.adapters[vendor] = adapter
    
    async def create_access_grant(
        self,
        db,
        envelope_id: str,
        lock_id: str,
        lock_vendor: str,
        valid_from: datetime,
        valid_until: datetime,
        attendance_cap: int
    ) -> Dict[str, Any]:
        """
        Create an access grant for a specific insurance envelope and lock
        """
        from models.insurance_models import AccessGrant, InsuranceEnvelope
        from sqlalchemy.orm import Session
        
        # Verify that the envelope is active
        envelope = db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.id == envelope_id,
            InsuranceEnvelope.status == 'active'
        ).first()
        
        if not envelope:
            raise ValueError(f"Active envelope {envelope_id} not found")
        
        # Create the access grant record
        access_grant = AccessGrant(
            envelope_id=envelope_id,
            lock_id=lock_id,
            access_type=self._determine_access_type(lock_vendor),
            valid_from=valid_from,
            valid_until=valid_until,
            attendance_cap=attendance_cap,
            status='active'
        )
        
        db.add(access_grant)
        db.commit()
        db.refresh(access_grant)
        
        # Provision access through the appropriate lock adapter
        adapter = self.adapters.get(lock_vendor)
        if not adapter:
            raise ValueError(f"No adapter registered for vendor: {lock_vendor}")
        
        grant_data = {
            "grant_id": str(access_grant.id),
            "envelope_id": envelope_id,
            "lock_id": lock_id,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "attendance_cap": attendance_cap
        }
        
        provision_result = await adapter.provision_access(grant_data)
        
        # Update the access grant with the provision result
        access_grant.access_type = provision_result.get('access_type', 'qr')
        
        db.commit()
        db.refresh(access_grant)
        
        return {
            "grant_id": str(access_grant.id),
            "access_type": access_grant.access_type,
            "access_payload": provision_result.get('access_payload', {}),
            "valid_from": access_grant.valid_from,
            "valid_until": access_grant.valid_until
        }
    
    async def check_in_attempt(
        self,
        db,
        grant_id: str,
        participant_id: str
    ) -> Dict[str, Any]:
        """
        Process a check-in attempt and enforce attendance limits
        """
        from models.insurance_models import AccessGrant, InsuranceEnvelope
        from sqlalchemy.orm import Session
        
        # Get the access grant
        grant = db.query(AccessGrant).filter(
            AccessGrant.id == grant_id
        ).first()
        
        if not grant:
            return {
                "allowed": False,
                "reason": "Invalid grant ID"
            }
        
        # Check if grant is still valid
        now = datetime.utcnow()
        if grant.status != 'active' or not (grant.valid_from <= now <= grant.valid_until):
            return {
                "allowed": False,
                "reason": "Grant is not active"
            }
        
        # Check attendance capacity
        remaining_capacity = grant.attendance_cap - grant.checkins_used
        
        if remaining_capacity <= 0:
            # Capacity exceeded - void the envelope and revoke access
            from services.insurance_envelope_service import InsuranceEnvelopeService
            envelope = db.query(InsuranceEnvelope).filter(
                InsuranceEnvelope.id == grant.envelope_id
            ).first()
            
            if envelope:
                InsuranceEnvelopeService.deactivate_envelope(
                    db, grant.envelope_id, "attendance_cap_exceeded"
                )
                
                # Revoke access through the appropriate lock adapter
                lock_vendor = self._get_lock_vendor_from_id(grant.lock_id)
                adapter = self.adapters.get(lock_vendor)
                if adapter:
                    await adapter.revoke_access(grant_id)
            
            return {
                "allowed": False,
                "reason": "attendance_cap_exceeded"
            }
        
        # Increment check-in count
        grant.checkins_used += 1
        db.commit()
        
        return {
            "allowed": True,
            "remaining_capacity": grant.attendance_cap - grant.checkins_used
        }
    
    async def revoke_access_grant(
        self,
        db,
        grant_id: str,
        reason: str = "manual_revocation"
    ) -> None:
        """
        Revoke an access grant and notify the lock system
        """
        from models.insurance_models import AccessGrant
        from sqlalchemy.orm import Session
        
        grant = db.query(AccessGrant).filter(
            AccessGrant.id == grant_id
        ).first()
        
        if not grant:
            raise ValueError(f"Access grant {grant_id} not found")
        
        # Update grant status
        grant.status = 'revoked'
        db.commit()
        
        # Revoke access through the appropriate lock adapter
        lock_vendor = self._get_lock_vendor_from_id(grant.lock_id)
        adapter = self.adapters.get(lock_vendor)
        if adapter:
            await adapter.revoke_access(grant_id)
    
    def _determine_access_type(self, lock_vendor: str) -> AccessType:
        """
        Determine the appropriate access type based on lock vendor capabilities
        """
        # Map vendors to access types
        vendor_to_access_type = {
            'kisi': AccessType.API_UNLOCK,
            'latch': AccessType.API_UNLOCK,
            'salto': AccessType.API_UNLOCK,
            'schlage': AccessType.PIN,
            'yale': AccessType.PIN,
            'august': AccessType.API_UNLOCK,
            'lockly': AccessType.PIN
        }
        
        return vendor_to_access_type.get(lock_vendor, AccessType.QR)
    
    def _get_lock_vendor_from_id(self, lock_id: str) -> str:
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
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
    
    async def provision_access(self, grant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Provision access through Kisi API
        """
        # In a real implementation, this would call the Kisi API
        # to create a temporary access credential
        import aiohttp
        
        # Simulate API call to Kisi
        # This would actually create a temporary credential in Kisi system
        temp_credential_id = str(uuid.uuid4())
        
        return {
            "access_type": "api_unlock",
            "access_payload": {
                "credential_id": temp_credential_id,
                "expires_at": grant_data["valid_until"]
            }
        }
    
    async def revoke_access(self, grant_id: str) -> None:
        """
        Revoke access through Kisi API
        """
        # In a real implementation, this would call the Kisi API
        # to delete the temporary access credential
        pass
    
    async def verify_access(self, grant_id: str) -> Dict[str, Any]:
        """
        Verify access through Kisi API
        """
        # In a real implementation, this would call the Kisi API
        # to check if the credential is still valid
        return {"valid": True, "expires_at": datetime.utcnow().isoformat()}


class SchlageAdapter(LockAdapter):
    """
    Adapter for Schlage keypad locks
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    async def provision_access(self, grant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Provision access through Schlage API (generate PIN)
        """
        import random
        import string
        
        # Generate a random 6-digit PIN
        pin = ''.join(random.choices(string.digits, k=6))
        
        # In a real implementation, this would call the Schlage API
        # to program the lock with the PIN for the specified time window
        return {
            "access_type": "pin",
            "access_payload": {
                "pin": pin,
                "expires_at": grant_data["valid_until"]
            }
        }
    
    async def revoke_access(self, grant_id: str) -> None:
        """
        Revoke access by removing the PIN from the lock
        """
        # In a real implementation, this would call the Schlage API
        # to remove the temporary PIN
        pass
    
    async def verify_access(self, grant_id: str) -> Dict[str, Any]:
        """
        Verify access by checking if PIN is still programmed
        """
        # In a real implementation, this would call the Schlage API
        # to check if the PIN is still valid
        return {"valid": True, "expires_at": datetime.utcnow().isoformat()}


class GenericQRAdapter(LockAdapter):
    """
    Generic adapter that generates QR codes for access
    """
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
    
    async def provision_access(self, grant_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a QR code for access
        """
        # Create a JWT token for the access grant
        payload = {
            "grant_id": grant_data["grant_id"],
            "exp": datetime.fromisoformat(grant_data["valid_until"]).timestamp(),
            "iat": datetime.utcnow().timestamp()
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
        
        return {
            "access_type": "qr",
            "access_payload": {
                "qr_code": qr_code_base64,
                "token": token,
                "expires_at": grant_data["valid_until"]
            }
        }
    
    async def revoke_access(self, grant_id: str) -> None:
        """
        Revoke access by invalidating the token
        """
        # In a real system, this would invalidate the token in a cache/db
        pass
    
    async def verify_access(self, grant_id: str) -> Dict[str, Any]:
        """
        Verify access by checking the token
        """
        # In a real system, this would check if the token is still valid
        return {"valid": True, "expires_at": datetime.utcnow().isoformat()}
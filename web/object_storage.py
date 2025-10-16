"""
Replit Object Storage Service
Handles image uploads and retrieval using Google Cloud Storage
"""
import os
import uuid
from datetime import datetime, timedelta
from google.cloud import storage
from google.cloud.storage import Blob
from google.auth import external_account
import httpx
from typing import Optional

REPLIT_SIDECAR_ENDPOINT = "http://127.0.0.1:1106"

class ObjectStorageService:
    """Service for interacting with Replit's object storage"""
    
    def __init__(self):
        # Create proper external account credentials
        credentials_info = {
            "type": "external_account",
            "audience": "replit",
            "subject_token_type": "access_token",
            "token_url": f"{REPLIT_SIDECAR_ENDPOINT}/token",
            "credential_source": {
                "url": f"{REPLIT_SIDECAR_ENDPOINT}/credential",
                "format": {
                    "type": "json",
                    "subject_token_field_name": "access_token",
                },
            },
            "universe_domain": "googleapis.com",
        }
        
        credentials = external_account.Credentials.from_info(credentials_info)
        self.client = storage.Client(credentials=credentials, project="")
    
    def get_private_object_dir(self) -> str:
        """Get the private object directory from environment"""
        dir_path = os.getenv("PRIVATE_OBJECT_DIR", "")
        if not dir_path:
            raise ValueError(
                "PRIVATE_OBJECT_DIR not set. Create a bucket in 'Object Storage' "
                "tool and set PRIVATE_OBJECT_DIR env var."
            )
        return dir_path
    
    async def get_upload_url(self, file_extension: str = "") -> str:
        """Generate a presigned upload URL for image uploads"""
        private_dir = self.get_private_object_dir()
        object_id = str(uuid.uuid4())
        
        # Add file extension if provided
        if file_extension:
            object_id = f"{object_id}{file_extension}"
        
        full_path = f"{private_dir}/card-images/{object_id}"
        bucket_name, object_name = self._parse_object_path(full_path)
        
        # Get presigned URL from Replit sidecar
        signed_url = await self._sign_object_url(
            bucket_name=bucket_name,
            object_name=object_name,
            method="PUT",
            ttl_sec=900  # 15 minutes
        )
        
        return signed_url
    
    def get_image_path(self, upload_url: str) -> str:
        """
        Convert upload URL to image path that can be stored in database
        Format: /images/card-images/{uuid}
        """
        private_dir = self.get_private_object_dir()
        if not private_dir.endswith("/"):
            private_dir = f"{private_dir}/"
        
        # Extract object name from GCS URL
        if upload_url.startswith("https://storage.googleapis.com/"):
            # Parse the URL to get the object path
            parts = upload_url.split("?")[0].split("/")
            # Find where the bucket name starts (after storage.googleapis.com/)
            bucket_start_idx = parts.index("storage.googleapis.com") + 1
            bucket_name = parts[bucket_start_idx]
            object_name = "/".join(parts[bucket_start_idx + 1:])
            
            # Reconstruct full path
            full_path = f"/{bucket_name}/{object_name}"
            
            # Extract the card-images part
            if f"{private_dir}card-images/" in full_path:
                image_id = full_path.split(f"{private_dir}card-images/")[1]
                return f"/images/card-images/{image_id}"
        
        return upload_url
    
    async def get_image_blob(self, image_path: str) -> Optional[Blob]:
        """Get the blob object for an image path"""
        if not image_path.startswith("/images/card-images/"):
            return None
        
        # Extract image ID from path
        image_id = image_path.replace("/images/card-images/", "")
        private_dir = self.get_private_object_dir()
        full_path = f"{private_dir}/card-images/{image_id}"
        
        bucket_name, object_name = self._parse_object_path(full_path)
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        
        # Check if exists
        if not blob.exists():
            return None
        
        return blob
    
    def _parse_object_path(self, path: str) -> tuple[str, str]:
        """Parse object path into bucket name and object name"""
        if not path.startswith("/"):
            path = f"/{path}"
        
        parts = path.split("/")
        if len(parts) < 3:
            raise ValueError("Invalid path: must contain at least a bucket name")
        
        bucket_name = parts[1]
        object_name = "/".join(parts[2:])
        
        return bucket_name, object_name
    
    async def _sign_object_url(
        self,
        bucket_name: str,
        object_name: str,
        method: str,
        ttl_sec: int
    ) -> str:
        """Get signed URL from Replit sidecar"""
        expires_at = (datetime.utcnow() + timedelta(seconds=ttl_sec)).isoformat()
        
        request_data = {
            "bucket_name": bucket_name,
            "object_name": object_name,
            "method": method,
            "expires_at": expires_at
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{REPLIT_SIDECAR_ENDPOINT}/object-storage/signed-object-url",
                json=request_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                raise Exception(
                    f"Failed to sign object URL, status: {response.status_code}, "
                    f"make sure you're running on Replit"
                )
            
            data = response.json()
            return data["signed_url"]

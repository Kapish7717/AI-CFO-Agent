import os
import logging
from supabase import create_client, Client

logger = logging.getLogger("db.storage")

# Retrieve Supabase credentials from environment
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
BUCKET_NAME = "cfo-agent-files"

_supabase_client = None

def get_storage_client() -> Client:
    """Initializes and returns the Supabase client if credentials are configured."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            logger.info(f"Initializing Supabase Client (URL: {SUPABASE_URL})")
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            
            # Proactively try to ensure the bucket exists
            try:
                buckets = _supabase_client.storage.list_buckets()
                bucket_names = [b.name for b in buckets]
                if BUCKET_NAME not in bucket_names:
                    logger.info(f"Creating public Supabase bucket '{BUCKET_NAME}'...")
                    _supabase_client.storage.create_bucket(BUCKET_NAME, options={"public": True})
            except Exception as bucket_err:
                logger.warning(f"Could not list/create storage bucket '{BUCKET_NAME}': {bucket_err}. Assuming it exists.")
                
            return _supabase_client
        except Exception as init_err:
            logger.error(f"Failed to initialize Supabase client: {init_err}")
            return None
    return None

def upload_to_storage(local_path: str, remote_path: str) -> str:
    """
    Uploads a local file to Supabase Storage.
    Returns the public URL if successful, or the local path if cloud storage is disabled/failed.
    """
    client = get_storage_client()
    if not client:
        logger.debug("Supabase client not active. Skipping upload, returning local path.")
        return local_path

    if not os.path.exists(local_path):
        logger.error(f"Local file does not exist for upload: {local_path}")
        return local_path

    # Normalize remote path separators
    remote_path = remote_path.replace("\\", "/")
    try:
        with open(local_path, "rb") as f:
            file_data = f.read()

        logger.info(f"Uploading {local_path} to Supabase bucket '{BUCKET_NAME}' at '{remote_path}'...")
        client.storage.from_(BUCKET_NAME).upload(
            path=remote_path,
            file=file_data,
            file_options={"upsert": "true"}
        )
        # Get public URL
        public_url = client.storage.from_(BUCKET_NAME).get_public_url(remote_path)
        logger.info(f"Successfully uploaded. Public URL: {public_url}")
        return public_url
    except Exception as e:
        logger.error(f"Failed to upload to Supabase Storage: {e}")
        return local_path

def download_from_storage(remote_path: str, local_path: str) -> bool:
    """
    Downloads a file from Supabase Storage and saves it to local_path.
    Returns True if successful, False otherwise.
    """
    client = get_storage_client()
    if not client:
        logger.debug("Supabase client not active. Skipping download.")
        return False

    remote_path = remote_path.replace("\\", "/")
    try:
        logger.info(f"Downloading '{remote_path}' from Supabase bucket '{BUCKET_NAME}' to '{local_path}'...")
        res = client.storage.from_(BUCKET_NAME).download(remote_path)
        
        # Ensure parent folder exists
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        
        with open(local_path, "wb") as f:
            f.write(res)
            
        logger.info(f"Successfully downloaded to '{local_path}'.")
        return True
    except Exception as e:
        # Don't log full exception stack for normal 404 (file not found/initialized yet)
        if "The resource was not found" in str(e) or "Object not found" in str(e) or "404" in str(e):
            logger.info(f"File '{remote_path}' not found in Supabase Storage bucket (expected if not generated yet).")
        else:
            logger.error(f"Failed to download from Supabase Storage: {e}")
        return False

def get_public_url(remote_path: str) -> str:
    """Gets the public URL of a remote file path in storage."""
    client = get_storage_client()
    if not client:
        return ""
    remote_path = remote_path.replace("\\", "/")
    return client.storage.from_(BUCKET_NAME).get_public_url(remote_path)

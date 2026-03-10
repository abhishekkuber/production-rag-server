from supabase import create_client, Client
from src.config.index import app_config

supabase: Client = create_client(
        supabase_url=app_config['supabase_api_url'],
        supabase_key=app_config['supabase_service_key']
    )
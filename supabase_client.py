"""
UpQuest – Supabase client singleton
"""

import os
from supabase import create_client, Client

_client: Client | None = None


def get_supabase_client() -> Client:
    """
    Returns a singleton Supabase client using the service-role key
    (bypasses RLS for server-side operations).
    """
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        _client = create_client(url, key)
    return _client

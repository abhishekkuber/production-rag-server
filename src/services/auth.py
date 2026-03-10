from src.config.index import app_config
from clerk_backend_api import AuthenticateRequestOptions, Clerk
from fastapi import Request, HTTPException



def get_current_user_clerk_id(request: Request) -> str:
    clerk_client = Clerk(bearer_auth=app_config['clerk_secret_key'])
    try: 
        request_state = clerk_client.authenticate_request(
            request, 
            AuthenticateRequestOptions(
                authorized_parties=app_config['domain']
            )
        )
        if not request_state.is_signed_in:
            raise HTTPException(status_code=401, detail="User is not signed in")
        
        clerk_id = request_state.payload.get("sub")
        if not clerk_id:
            raise HTTPException(status_code=401, detail="Clerk ID not found in token")
        
        return clerk_id
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Clerk Authentication Failed : {str(e)}"
        )
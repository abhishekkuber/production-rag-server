from fastapi import APIRouter, Depends, HTTPException
from src.services.database import supabase
from src.services.auth import get_current_user_clerk_id
from src.models.index import ChatCreate

router = APIRouter(
    tags=["chats"],
)


# Create a chat
@router.post("/")
async def create_chat(
    chat: ChatCreate,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        created_chat = supabase.table("chats").insert({
            "title": chat.title,
            "project_id": chat.project_id,
            "clerk_id": clerk_id
        }).execute()

        if not created_chat.data:
            raise HTTPException(status_code=422, detail="Failed to create chat. Invalid data provided.")

        return {
            "message": "Chat created successfully",
            "data": created_chat.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create chat. Reason: {str(e)}")
    
# Delete a chat
@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        delete_result = supabase.table("chats").delete().eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if not delete_result.data:
            raise HTTPException(status_code=404, detail=f"Chat not found / Access denied.")
        
        return {
            "message": "Chat deleted successfully",
            "data": delete_result.data[0]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete chat. Reason: {str(e)}")
    

# Get the messages of the chat
@router.get("/{chat_id}")
async def get_chat(
    chat_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        # Get the chat and verify it belongs to the user AND has a project id
        chat_verification_result = supabase.table("chats").select("*").eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if not chat_verification_result.data[0]:
            raise HTTPException(status_code=404, detail=f"Chat not found / Access denied.")
        
        chat_result = chat_verification_result.data[0]
        
        messages_result = supabase.table("messages").select("*").eq("chat_id", chat_id).eq("clerk_id", clerk_id).order('created_at', desc=False).execute()
        chat_result['messages'] = messages_result.data or []

        return {
            "message": "Chat retrieved successfully",
            "data": chat_result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Chat {chat_id}. Reason: {str(e)}")

from fastapi import APIRouter, Depends, HTTPException
from src.services.database import supabase
from src.services.auth import get_current_user_clerk_id
from src.models.index import ChatCreate
from src.config.logging import get_logger, set_project_id, set_user_id

logger = get_logger(__name__)

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
        set_project_id(chat.project_id)
        set_user_id(clerk_id)
        logger.info("creating_chat", title=chat.title)

        created_chat = supabase.table("chats").insert({
            "title": chat.title,
            "project_id": chat.project_id,
            "clerk_id": clerk_id
        }).execute()

        if not created_chat.data:
            logger.warning( "chat_creation_failed", reason="invalid_data")
            raise HTTPException(status_code=422, detail="Failed to create chat. Invalid data provided.")

        chat_id = created_chat.data[0].get("id")
        logger.info("chat_created_successfully", chat_id=chat_id)

        return {
            "message": "Chat created successfully",
            "data": created_chat.data[0]
        }
    except Exception as e:
        logger.error("chat_creation_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create chat. Reason: {str(e)}")
    
# Delete a chat
@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    set_user_id(clerk_id)
    logger.info("deleting_chat", chat_id=chat_id)
    try:
        delete_result = supabase.table("chats").delete().eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if delete_result.data:
            set_project_id(delete_result.data[0].get("project_id"))
        
        if not delete_result.data:
            logger.warning("chat_deletion_failed", chat_id=chat_id, reason="not_found_or_authorized")
            raise HTTPException(status_code=404, detail=f"Chat not found / Access denied.")
        
        logger.info("chat_deleted_successfully", chat_id=chat_id)
        return {
            "message": "Chat deleted successfully",
            "data": delete_result.data[0]
        }
    
    except Exception as e:
        logger.error("chat_deletion_error", chat_id=chat_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete chat. Reason: {str(e)}")
    

# Get the messages of the chat
@router.get("/{chat_id}")
async def get_chat(
    chat_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    set_user_id(clerk_id)
    try:
        # Get the chat and verify it belongs to the user AND has a project id
        chat_verification_result = supabase.table("chats").select("*").eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if not chat_verification_result.data[0]:
            raise HTTPException(status_code=404, detail=f"Chat not found / Access denied.")
        
        chat_result = chat_verification_result.data[0]
        set_project_id(chat_result.get("project_id"))
        
        messages_result = supabase.table("messages").select("*").eq("chat_id", chat_id).eq("clerk_id", clerk_id).order('created_at', desc=False).execute()
        chat_result['messages'] = messages_result.data or []

        return {
            "message": "Chat retrieved successfully",
            "data": chat_result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Chat {chat_id}. Reason: {str(e)}")

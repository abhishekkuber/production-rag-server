from fastapi import APIRouter, Depends, HTTPException
from database import supabase 
from pydantic import BaseModel
from auth import get_current_user

router = APIRouter(
    tags=["chats"]
)

class ChatCreate(BaseModel):
    title: str
    project_id: str


# Create a chat
@router.post("/api/chats")
async def create_chat(
    chat: ChatCreate,
    clerk_id: str=Depends(get_current_user)
):
    try:
        created_chat = supabase.table("chats").insert({
            "title": chat.title,
            "project_id": chat.project_id,
            "clerk_id": clerk_id
        }).execute()

        return {
            "message": "Chat created successfully",
            "data": created_chat.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create chat : {str(e)}")
    
# Delete a chat
@router.delete("/api/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        delete_result = supabase.table("chats").delete().eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if not delete_result:
            raise HTTPException(status_code=404, detail=f"Chat deletion failed : {str(e)}")
        
        return {
            "message": "Chat deleted successfully",
            "data": delete_result.data[0]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete chat : {str(e)}")
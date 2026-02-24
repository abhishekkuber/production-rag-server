from fastapi import APIRouter, Depends, HTTPException
from database import supabase 
from pydantic import BaseModel
from auth import get_current_user

router = APIRouter(
    tags=["files"]
)

# Get all the files of a certain project - FK constraints  ensures 
@router.get("/api/projects/{project_id}/files")
def get_project_files(
    project_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        project_documents = supabase.table("project_documents").select("*").eq("project_id", project_id).eq("clerk_id", clerk_id).order("created_at", desc=True).execute()
        # We couldve done this, but by default there are no files associated with a new project. 
        # And anyways, we are handling it by returning a [] if the project_documents.data doesnt exist
        
        # if not project_documents.data:
        #     raise HTTPException(status_code=404, detail=f"Project files not found / Access denied : {str(e)}")
        
        return {
            "message": "Project files fetched successfully",
            "data": project_documents.data or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch project files : {str(e)}")
    
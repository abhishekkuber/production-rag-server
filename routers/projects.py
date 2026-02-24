from fastapi import APIRouter, Depends, HTTPException
from database import supabase 
from pydantic import BaseModel
from auth import get_current_user

router = APIRouter(
    tags=["projects"]
)

class ProjectCreate(BaseModel):
    name: str
    description: str=""

# API to get the projects of a user.
@router.get("/api/projects")
async def get_projects(clerk_id: str = Depends(get_current_user)): 
    try:
        result = supabase.table('projects').select("*").eq('clerk_id', clerk_id).execute()

        return {
            "message": "Projects fetched successfully",
            "data": result.data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get projects : {str(e)}")

# API to create a project
@router.post("/api/projects")
async def create_project(project: ProjectCreate, clerk_id=Depends(get_current_user)):
    try:
        project_result = supabase.table('projects').insert({
            "clerk_id": clerk_id,
            "name": project.name,
            "description": project.description
        }).execute()

        if not project_result.data:
            raise HTTPException(status_code=500, detail=f"Failed to create project : {str(e)}")
        
        created_project = project_result.data[0]
        
        project_result = supabase.table('project_settings').insert({
            "project_id": created_project["id"], # get the uuid of the newly created project
            "embedding_model": "text-embedding-3-large",
            "rag_strategy": "basic",
            "agent_type": "agentic",
            "chunks_per_search": 10,
            "final_context_size": 5,
            "similarity_threshold": 0.3,
            "number_of_queries": 5,
            "reranking_enabled": True,
            "reranking_model": "rerank-english-v3.0",
            "vector_weight": 0.7,
            "keyword_weight": 0.3,
        }).execute()

        if not project_result.data:
            supabase.table("projects").delete().eq("id", created_project["id"]).execute()
            raise HTTPException(status_code=500, detail=f"Failed to create project settings : {str(e)}")
        

        return {
            "message": "Project created successfully",
            "data": created_project
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project creation failed : {str(e)}")
    


# Delete project
@router.delete("/api/projects/{project_id}") # delete the project based on the project id
def delete_project(
    project_id: str,
    clerk_id: str = Depends(get_current_user)
): 
    try:
        project_result = supabase.table("projects").select("*").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not project_result:
            raise HTTPException(status_code=404, detail=f"Project not found / Access denied : {str(e)}")
        
        delete_result = supabase.table("projects").delete().eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not delete_result:
            raise HTTPException(status_code=500, detail=f"Project deletion failed : {str(e)}")
        
        return {
            "message": "Project deleted successfully",
            "data": delete_result.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project : {str(e)}")

# Get a certain project
@router.get("/api/projects/{project_id}")
def get_project(
    project_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        project = supabase.table("projects").select("*").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not project.data:
            raise HTTPException(status_code=404, detail=f"Project not found / Access denied : {str(e)}")
        
        return {
            "message": "Project fetched successfully",
            "data": project.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch project : {str(e)}")

# Get the chats of a certain project
@router.get("/api/projects/{project_id}/chats")
def get_project_chats(
    project_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        project_chats = supabase.table("chats").select("*").eq("project_id", project_id).eq("clerk_id", clerk_id).order("created_at", desc=True).execute()
        # if not project_chats.data:
        #     raise HTTPException(status_code=404, detail=f"Project chats not found / Access denied : {str(e)}")
        
        return {
            "message": "Project chats fetched successfully",
            "data": project_chats.data or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch project chats : {str(e)}")
    
# Get the project settings of a certain project
@router.get("/api/projects/{project_id}/settings")
def get_project_settings(
    project_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        # you can also skip .eq("clerk_id", clerk_id) because the project settings is sensitive data
        project_settings = supabase.table("project_settings").select("*").eq("project_id", project_id).execute()
        if not project_settings.data:
            raise HTTPException(status_code=404, detail=f"Project settings not found / Access denied : {str(e)}")
        
        return {
            "message": "Project settings fetched successfully",
            "data": project_settings.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch project settings : {str(e)}")
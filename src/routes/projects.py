from fastapi import APIRouter, Depends, HTTPException
from src.services.database import supabase
from src.services.auth import get_current_user_clerk_id
from src.models.index import ProjectCreate, ProjectSettings, SendMessageRequest, MessageRole
from src.rag.retrieval.index import retrieve_context_and_build_prompt
from src.rag.retrieval.utils import prepare_prompt_and_invoke_llm

router = APIRouter(
    tags=["projects"]
)


"""
`/api/projects`

  - GET `/api/projects/` ~ List all projects
  - POST `/api/projects/` ~ Create a new project
  - DELETE `/api/projects/{project_id}` ~ Delete a specific project
  
  - GET `/api/projects/{project_id}` ~ Get specific project data
  - GET `/api/projects/{project_id}/chats` ~ Get specific project chats
  - GET `/api/projects/{project_id}/settings` ~ Get specific project settings
  
  - PUT `/api/projects/{project_id}/settings` ~ Update specific project settings
  - POST `/api/projects/{project_id}/chats/{chat_id}/messages` ~ Send a message to a Specific Chat
  
"""


@router.get("/")
async def get_projects(clerk_id: str = Depends(get_current_user_clerk_id)): 
    try:
        result = supabase.table('projects').select("*").eq('clerk_id', clerk_id).execute()

        return {
            "message": "Projects fetched successfully",
            "data": result.data or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get projects. Reason: {str(e)}")


@router.post("/")
async def create_project(project: ProjectCreate, clerk_id=Depends(get_current_user_clerk_id)):
    try:
        project_result = supabase.table('projects').insert({
            "clerk_id": clerk_id,
            "name": project.name,
            "description": project.description
        }).execute()

        if not project_result.data:
            raise HTTPException(status_code=422, detail=f"Failed to create project - Invalid data provided")
        
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
            # Rollback
            supabase.table("projects").delete().eq("id", created_project["id"]).execute()
            raise HTTPException(status_code=422, detail=f"Failed to create project settings. Project creation rolled back.")
        
        return {
            "message": "Project created successfully",
            "data": created_project
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project creation failed. Reason: {str(e)}")
    

@router.delete("/{project_id}") # delete the project based on the project id
def delete_project(
    project_id: str,
    clerk_id: str = Depends(get_current_user_clerk_id)
): 
    try:
        project_result = supabase.table("projects").select("*").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not project_result:
            raise HTTPException(status_code=404, detail=f"Project not found / Access denied.")
        
        delete_result = supabase.table("projects").delete().eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not delete_result:
            raise HTTPException(status_code=500, detail=f"Project deletion failed. Please try again.")
        
        return {
            "message": "Project deleted successfully",
            "data": delete_result.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project. Reason: {str(e)}")

# Get a certain project
@router.get("/{project_id}")
def get_project(
    project_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        project_result = supabase.table("projects").select("*").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not project_result.data:
            raise HTTPException(status_code=404, detail=f"Project not found / Access denied.")
        
        return {
            "message": "Project fetched successfully",
            "data": project_result.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch project. Reason: {str(e)}")

# Get the chats of a certain project
@router.get("/{project_id}/chats")
def get_project_chats(
    project_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        project_chats = supabase.table("chats").select("*").eq("project_id", project_id).eq("clerk_id", clerk_id).order("created_at", desc=True).execute()
        
        return {
            "message": "Project chats fetched successfully",
            "data": project_chats.data or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch project chats. Reason: {str(e)}")
    
# Get the project settings of a certain project
@router.get("/{project_id}/settings")
def get_project_settings(
    project_id: str
):
    try:
        project_settings = supabase.table("project_settings").select("*").eq("project_id", project_id).execute()
        if not project_settings.data:
            raise HTTPException(status_code=404, detail=f"Project settings not found.")
        
        return {
            "message": "Project settings fetched successfully",
            "data": project_settings.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch project settings. Reason: {str(e)}")

# Update the project settings of a certain project
@router.put("/{project_id}/settings")
def update_project_setting(
    project_id: str,
    settings: ProjectSettings,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        project_verification_result = supabase.table("projects").select("id").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        
        if not project_verification_result.data:
            raise HTTPException(status_code=404, detail=f"Project settings not found / Access denied.")
        
        # Convert the Pydantic model to a dictionary with settings.model_dump()
        update_result = supabase.table("project_settings").update(settings.model_dump()).eq("project_id", project_id).execute()
        if not update_result.data:
            raise HTTPException(status_code=422, detail=f"Failed to update project settings.")
        
        return {
            "message": "Project settings updated successfully", 
            "data": update_result.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update project settings for Project {project_id}. Reason: {str(e)}")
    



# Send a message and get the corresponding LLM response
@router.post("/{project_id}/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    project_id: str,
    request: SendMessageRequest,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        message = request.content
        print(f"Saving user message")
        user_message = supabase.table("messages").insert({
            "content": message,
            "role": MessageRole.USER.value,
            "chat_id": chat_id,
            "clerk_id": clerk_id,
        }).execute()
        print(f"User message saved")

        texts, images, tables, citations = retrieve_context_and_build_prompt(project_id, message)

        ai_response = prepare_prompt_and_invoke_llm(
            user_query=message,
            texts=texts,
            images=images,
            tables=tables,
        )

        ai_message = supabase.table("messages").insert({
            "content": ai_response,
            "role": MessageRole.ASSISTANT.value,
            "chat_id": chat_id,
            "clerk_id": clerk_id,
            "citations": citations
        }).execute()
        print(f"AI message saved")
        
        return {
            "message": "Messages sent successfully",
            "data": {
                "userMessage": user_message.data[0],
                "aiMessage": ai_message.data[0]
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send message. Reason: {str(e)}")
    

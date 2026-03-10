from src.services.database import supabase
from fastapi import HTTPException
from typing import List

def get_project_settings(project_id: str):
    try:
        project_settings = supabase.table("project_settings").select("*").eq("project_id", project_id).execute()
        if not project_settings.data:
            raise HTTPException(status_code=404, detail=f"Project settings not found / Access denied.")
        return project_settings.data[0]
    except Exception as e:
        raise Exception(f"Failed to get project settings. Reason: {str(e)}")

def get_project_documents(project_id: str):
    try:
        document_ids = supabase.table("project_documents").select("id").eq("project_id", project_id).execute()
        if not document_ids.data:
            # return []
            raise Exception(f"No documents found for Project {project_id}")
        
        document_ids = [doc['id'] for doc in document_ids.data]
        return document_ids
    except Exception as e:
        raise Exception(f"Failed to get document IDs related to Project {project_id}. Reason: {str(e)}")
    

def get_document_filenames(document_ids: List[str]):
    try:
        result = supabase.table('project_documents').select('id', 'filename').in_('id', document_ids).execute()
        filename_map = {doc['id']: doc['filename'] for doc in result.data}
        return filename_map
    except Exception as e:
        raise Exception(f"Failed to get filenames. Reason: {str(e)}")

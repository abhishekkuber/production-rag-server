import uuid
from fastapi import APIRouter, Depends, HTTPException
from database import supabase, s3_client, BUCKET_NAME
from pydantic import BaseModel
from auth import get_current_user
from tasks import process_document

router = APIRouter(
    tags=["files"]
)

class FileUploadRequest(BaseModel):
    filename: str
    file_size: int
    file_type: str

class FileConfirmResponse(BaseModel):
    s3_key: str

class UrlAddRequest(BaseModel):
    url: str
    

# Get all the files of a certain project - FK constraints  ensures 
@router.get("/api/projects/{project_id}/files")
async def get_project_files(
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
    
# API to get presigned URL
@router.post("/api/projects/{project_id}/file/upload-url")
async def get_upload_url(
    project_id: str,
    file_request: FileUploadRequest,
    clerk_id: str=Depends(get_current_user)
):
    try:
        # Check project exists and belongs to the user
        result = supabase.table("projects").select("id").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Project not found / Access denied : {str(e)}")
        
        # Generate unique s3 key
        file_extension = file_request.filename.split('.')[-1] if '.' in file_request.filename else ''
        unique_id = str(uuid.uuid4())
        s3_key = f"projects/{project_id}/documents/{unique_id}.{file_extension}"

        # Generate the presigned url (will expire in 1 hour)
        presigned_url = s3_client.generate_presigned_url(
            "put_object", # for which operation is this presigned url getting uploaded?
            Params={
                "Bucket": BUCKET_NAME,
                "Key": s3_key,
                "ContentType": file_request.file_type
            },
            ExpiresIn=3600
        )
        
        # Create a DB record with pending status
        file_result = supabase.table("project_documents").insert({
            "project_id": project_id,
            "filename": file_request.filename,
            "s3_key": s3_key,
            "file_size": file_request.file_size,
            "file_type": file_request.file_type,
            "processing_status": "uploading",
            "clerk_id": clerk_id
        }).execute()

        if not file_result.data:
            raise HTTPException(status_code=500, detail=f"Failed to create document record")
        
        return {
            "message": "Presigned URL generated successfully",
            "data": {
                "upload_url": presigned_url,
                "s3_key": s3_key,
                "document": file_result.data[0]
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get presigned URL : {str(e)}")


# API to get confirmation from client about document upload
@router.post("/api/projects/{project_id}/file/confirm")
async def confirm_file_upload(
    project_id: str,
    confirm_request: FileConfirmResponse,
    clerk_id: str=Depends(get_current_user)
):
    try:
        s3_key = confirm_request.s3_key
        if not s3_key: 
            raise HTTPException(status_code=400, detail="S3 key is required")
        
        result = supabase.table("project_documents").update({
            "processing_status": "queued"
        }).eq("s3_key", s3_key).eq("clerk_id", clerk_id).eq("project_id", project_id).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail=f"Document not found / Access denied")
        
        document_id = result.data[0]["id"]
        # Start background preprocessing of the current file 
        # Store task_id so that we can track it later if needed
        task = process_document.delay(document_id)
        # Update the document task_id to the task id of the celery task
        result = supabase.table("project_documents").update({
            "task_id": task.id
        }).eq("id", document_id).execute()

        return {
            "message": "Upload confirmed, processing started with Celery",
            "data": result.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to confirm upload : {str(e)}")


# API to get the website URL from the frontend
@router.post("/api/projects/{project_id}/urls")
async def add_website_url(
    project_id: str,
    website_url: UrlAddRequest,
    clerk_id: str=Depends(get_current_user)
):
    try:
        # validate url
        url = website_url.url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        print(f"URL from inside the server : {url}")

        url_add_result = supabase.table("project_documents").insert({
            "project_id": project_id,
            "filename": url,
            "s3_key": "", # because it is not a document that will be stored in the s3 storage
            "file_size": 0,
            "file_type": "text/html",
            "processing_status": "queued", # no time needed to add it to s3
            "source_url": url,
            "source_type": "url",
            "clerk_id": clerk_id
        }).execute()

        if not url_add_result.data:
            raise HTTPException(status_code=500, detail=f"Failed to create URL record")

        document_id = url_add_result.data[0]["id"]
        task = process_document.delay(document_id)
        # Triggers the 'process_document' function asynchronously using .delay().
        # This sends a message to the broker; the worker picks it up and runs it in the background.
        
        result = supabase.table("project_documents").update({
            "task_id": task.id
        }).eq("id", document_id).execute()
        # Updates the 'project_documents' table in Supabase.
        # It stores the 'task.id' (the Celery unique identifier) to allow the frontend or backend to check the task's status later.

        return {
            "message": "URL added successfully",
            "data": url_add_result.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add URL : {str(e)}")

@router.delete("/api/projects/{project_id}/files/{file_id}")
async def delete_file(
    project_id: str,
    file_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        # Get the file record
        search_result =  supabase.table("project_documents").select("*").eq("id", file_id).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        if not search_result:
            raise HTTPException(status_code=404, detail=f"Document not found / Access denied : {str(e)}")
        
        s3_key = search_result.data[0]["s3_key"]
        if s3_key:
            try:
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
                print("Deleted from S3")

            except Exception as e:
                print("Failed to delete from S3")
                raise HTTPException(status_code=500, detail=f"Failed to delete file from S3 : {str(e)}")

            
        delete_result = supabase.table("project_documents").delete().eq("id", file_id).execute()
        if not delete_result.data:
            raise HTTPException(status_code=500, detail=f"Document deletion failed : {str(e)}")
        
        return {
            "message": "Files deleted successfully",
            "data": delete_result.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document : {str(e)}")


@router.get("/api/projects/{project_id}/files/{file_id}/chunks")
async def get_chunks(
    project_id: str,
    file_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        # see if the project exists 
        project_result = supabase.table("projects").select("id").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not project_result.data:
            raise HTTPException(status_code=404, detail=f"Project not found / Access denied : {str(e)}")
        
        # See if the document exists
        document_result = supabase.table("project_documents").select('id').eq('id', file_id).eq('project_id', project_id).execute()
        if not document_result.data:
            raise HTTPException(status_code=404, detail=f"Document not found / Access denied : {str(e)}")
        
        chunks_result = supabase.table("document_chunks").select("*").eq("document_id", file_id).order('chunk_index').execute()

        return {
            "message": "Document chunks retrieved successfully",
            "data": chunks_result.data or []
        }
        
    except Exception as e:
        print(f"Error fetching chunks")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve document chunks : {str(e)}")
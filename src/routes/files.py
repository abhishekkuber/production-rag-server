import uuid
from fastapi import APIRouter, Depends, HTTPException
from src.config.index import app_config
from src.services.database import supabase
from src.services.auth import get_current_user_clerk_id
from src.utils.index import validate_url
from src.services.aws_s3 import s3_client
from src.services.celery import perform_rag_ingestion
from src.models.index import FileUploadRequest, FileConfirmResponse, UrlAddRequest, ProcessingStatus

router = APIRouter(
    tags=["files"],
)

"""
`/api/projects`

  - GET `/{project_id}/files` ~ List all project files
  - POST `/{project_id}/files/upload-url` ~ Generate presigned url for file upload for frontend
  - POST `/{project_id}/files/confirm` ~ Confirmation of file upload to S3
  - POST `/{project_id}/urls` ~ Add website URL to database
  - DELETE `/{project_id}/files/{file_id}` ~ Delete document from s3 and database
  - GET `/{project_id}/files/{file_id}/chunks` ~ Get project document chunks
"""



@router.get("/{project_id}/files")
async def get_project_files(
    project_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        project_documents = supabase.table("project_documents").select("*").eq("project_id", project_id).eq("clerk_id", clerk_id).order("created_at", desc=True).execute()
        return {
            "message": "Project files fetched successfully",
            "data": project_documents.data or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch project files for Project ID {project_id}. Reason: {str(e)}")


# API to get presigned URL
@router.post("/{project_id}/file/upload-url")
async def get_upload_url(
    project_id: str,
    file_request: FileUploadRequest,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    """
    ! Logic Flow:
    * 1. Verify project exists and belongs to the current user
    * 2. Generate s3 key
    * 3. Generate upload presigned url (will expire in 1 hour)
    * 4. Create project document record with pending status
    * 5. Return presigned url
    """
    try:
        # Check project exists and belongs to the user
        result = supabase.table("projects").select("id").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Project not found / Access denied.")
        
        # Generate unique s3 key
        file_extension = file_request.filename.split('.')[-1] if '.' in file_request.filename else ''
        unique_id = str(uuid.uuid4())
        s3_key = f"projects/{project_id}/documents/{unique_id}.{file_extension}" if file_extension else f"projects/{project_id}/documents/{unique_id}"

        # Generate the presigned url (will expire in 1 hour)
        presigned_url = s3_client.generate_presigned_url(
            "put_object", # for which operation is this presigned url getting uploaded?
            Params={
                "Bucket": app_config['s3_bucket_name'],
                "Key": s3_key,
                "ContentType": file_request.file_type
            },
            ExpiresIn=3600
        )

        if not presigned_url:
            raise HTTPException(status_code=422, detail=f"Failed to generate presigned URL")
        
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
            raise HTTPException(status_code=422, detail=f"Failed to create document record. Invalid data provided.")
        
        return {
            "message": "Presigned URL generated successfully",
            "data": {
                "upload_url": presigned_url,
                "s3_key": s3_key,
                "document": file_result.data[0]
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get presigned URL. Reason: {str(e)}")



# API to get confirmation from client about document upload
@router.post("/{project_id}/file/confirm")
async def confirm_file_upload(
    project_id: str,
    confirm_request: FileConfirmResponse,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    """
    ! Logic Flow:
    * 1. Verify S3 key is provided
    * 2. Verify file exists in database
    * 3. Update file status to "queued"
    * 4. Perform Celery - RAG Ingestion Task
    * 5. Update the project document record with the task_id
    * 6. Return successfully confirmed file upload data
    """
    try:
        s3_key = confirm_request.s3_key
        if not s3_key: 
            raise HTTPException(status_code=400, detail="S3 key is required")
        
        doc_verification_result = supabase.table("project_documents").select("id").eq("s3_key", s3_key).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        if not doc_verification_result.data:
            raise HTTPException(status_code=404, detail=f"File not found / Access denied.")
        
        doc_update_result = supabase.table("project_documents").update({
            "processing_status": ProcessingStatus.QUEUED
        }).eq("s3_key", s3_key).eq("clerk_id", clerk_id).eq("project_id", project_id).execute()

        if not doc_update_result.data:
            raise HTTPException(status_code=404, detail=f"Document not found / Access denied")
        

        # Start background preprocessing of the current file 
        document_id = doc_update_result.data[0]["id"]
        # Store task_id so that we can track it later if needed
        task = perform_rag_ingestion.delay(document_id)
        # Update the document task_id to the task id of the celery task
        doc_update_result = supabase.table("project_documents").update({
            "task_id": task.id
        }).eq("id", document_id).execute()
        
        if not doc_update_result.data:
            raise HTTPException(status_code=422, detail=f"Failed to update document record with task_id. Document : {document_id}.")

        return {
            "message": "Upload to S3 confirmed, background processing started.",
            "data": doc_update_result.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to confirm upload to S3. Reason: {str(e)}")



# API to get the website URL from the frontend
@router.post("/{project_id}/urls")
async def add_website_url(
    project_id: str,
    website_url: UrlAddRequest,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    try:
        # validate url
        url = website_url.url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        if not validate_url(url):
            raise HTTPException(status_code=400, detail=f"Invalid URL")

        url_add_result = supabase.table("project_documents").insert({
            "project_id": project_id,
            "filename": url,
            "s3_key": "", # because it is not a document that will be stored in the s3 storage
            "file_size": 0,
            "file_type": "text/html",
            "processing_status": ProcessingStatus.QUEUED,
            "source_url": url,
            "source_type": "url",
            "clerk_id": clerk_id
        }).execute()

        if not url_add_result.data:
            raise HTTPException(status_code=422, detail=f"Failed to create URL record. Invalid data provided.")

        document_id = url_add_result.data[0]["id"]
        task = perform_rag_ingestion.delay(document_id)
        
        doc_update_result = supabase.table("project_documents").update({
            "task_id": task.id
        }).eq("id", document_id).execute()

        if not doc_update_result.data:
            raise HTTPException(status_code=422, detail=f"Failed to update URL record with the task id.")

        return {
            "message": "URL added successfully, background processing started.",
            "data": url_add_result.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add URL. Reason: {str(e)}")


@router.delete("/{project_id}/files/{file_id}")
async def delete_file(
    project_id: str,
    file_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    """
    ! Logic Flow:
    * 1. Verify document exists and belongs to the current user and take complete project document record
    * 2. Delete file from S3 (only for actual files, not for URLs)
    * 3. Delete document from database
    * 4. Return successfully deleted document data
    """
    try:
        doc_verification_result =  supabase.table("project_documents").select("*").eq("id", file_id).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        if not doc_verification_result:
            raise HTTPException(status_code=404, detail=f"Document not found / Access denied.")
        
        s3_key = doc_verification_result.data[0]["s3_key"]
        if s3_key:
            try:
                s3_client.delete_object(Bucket=app_config['s3_bucket_name'], Key=s3_key)
                print("Deleted from S3")

            except Exception as e:
                print("Failed to delete from S3")
                raise HTTPException(status_code=500, detail=f"Failed to delete file from S3 : {str(e)}")
            
        delete_result = supabase.table("project_documents").delete().eq("id", file_id).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        if not delete_result.data:
            raise HTTPException(status_code=404, detail=f"Document deletion failed.")
        
        return {
            "message": "File deleted successfully",
            "data": delete_result.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document. Reason: {str(e)}")


@router.get("/{project_id}/files/{file_id}/chunks")
async def get_chunks(
    project_id: str,
    file_id: str,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    """
    ! Logic Flow:
    * 1. Verify document exists and belongs to the current user and Take complete project document record
    * 2. Get project document chunks
    * 3. Return project document chunks data
    """

    try:
        # See if the document exists and belongs to the user
        doc_verification_result = supabase.table("project_documents").select('id').eq('id', file_id).eq('project_id', project_id).eq("clerk_id", clerk_id).execute()
        if not doc_verification_result.data:
            raise HTTPException(status_code=404, detail=f"Document not found / Access denied.")
        
        chunks_result = supabase.table("document_chunks").select("*").eq("document_id", file_id).order('chunk_index').execute()

        return {
            "message": "Document chunks retrieved successfully",
            "data": chunks_result.data or []
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve document chunks. Reason: {str(e)}")
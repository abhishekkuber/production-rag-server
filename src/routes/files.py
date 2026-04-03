import uuid
from fastapi import APIRouter, Depends, HTTPException
from src.config.index import app_config
from src.services.database import supabase
from src.services.auth import get_current_user_clerk_id
from src.utils.index import validate_url
from src.services.aws_s3 import s3_client
from src.services.celery import perform_rag_ingestion
from src.models.index import FileUploadRequest, FileConfirmResponse, UrlAddRequest, ProcessingStatus
from src.config.logging import get_logger, set_project_id, set_user_id

logger = get_logger(__name__)

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
    set_project_id(project_id)
    set_user_id(clerk_id)
    try:
        logger.info("fetching_project_files")
        project_documents = supabase.table("project_documents").select("*").eq("project_id", project_id).eq("clerk_id", clerk_id).order("created_at", desc=True).execute()
        logger.info("project_files_retrieved", file_count=len(project_documents.data or []))
        return {
            "message": "Project files fetched successfully",
            "data": project_documents.data or []
        }
    except Exception as e:
        logger.error("project_files_retrieval_error", error=str(e), exc_info=True)
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
    set_project_id(project_id)
    set_user_id(clerk_id)
    try:
        # Check project exists and belongs to the user
        logger.info("generating_upload_url", filename=file_request.filename, file_size=file_request.file_size)
        result = supabase.table("projects").select("id").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not result.data:
            logger.warning("project_not_found_for_upload")
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
            logger.error("presigned_url_generation_failed", s3_key=s3_key)
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
            logger.error("document_record_creation_failed", filename=file_request.filename, reason="no_data_returned")
            raise HTTPException(status_code=422, detail=f"Failed to create document record. Invalid data provided.")
        
        logger.info("upload_url_generated_successfully", document_id=file_result.data[0]["id"], s3_key=s3_key)
        return {
            "message": "Presigned URL generated successfully",
            "data": {
                "upload_url": presigned_url,
                "s3_key": s3_key,
                "document": file_result.data[0]
            }
        }
    
    except Exception as e:
        logger.error("upload_url_generation_error", filename=file_request.filename, error=str(e), exc_info=True)
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
    set_project_id(project_id)
    set_user_id(clerk_id)
    try:
        s3_key = confirm_request.s3_key
        logger.info("confirming_file_upload", s3_key=s3_key)
        if not s3_key: 
            logger.warning("s3_key_missing")
            raise HTTPException(status_code=400, detail="S3 key is required")
        
        doc_verification_result = supabase.table("project_documents").select("id").eq("s3_key", s3_key).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        if not doc_verification_result.data:
            logger.warning("file_not_found_for_confirmation", s3_key=s3_key)
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
        logger.info("rag_ingestion_task_queued", document_id=document_id, task_id=task.id)
        doc_update_result = supabase.table("project_documents").update({
            "task_id": task.id
        }).eq("id", document_id).execute()
        
        if not doc_update_result.data:
            logger.error("task_id_update_failed", document_id=document_id, task_id=task.id, reason="no_data_returned")
            raise HTTPException(status_code=422, detail=f"Failed to update document record with task_id. Document : {document_id}.")

        logger.info("file_upload_confirmed_successfully", document_id=document_id, task_id=task.id)
        return {
            "message": "Upload to S3 confirmed, background processing started.",
            "data": doc_update_result.data[0]
        }
        
    except Exception as e:
        logger.error("file_confirmation_error", s3_key=s3_key, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to confirm upload to S3. Reason: {str(e)}")



# API to get the website URL from the frontend
@router.post("/{project_id}/urls")
async def add_website_url(
    project_id: str,
    website_url: UrlAddRequest,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    set_project_id(project_id)
    set_user_id(clerk_id)
    try:
        # validate url
        url = website_url.url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        logger.info("processing_url", url=url)
        if not validate_url(url):
            logger.warning("invalid_url", url=url)
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
            logger.error("url_document_creation_failed", url=url, reason="no_data_returned")
            raise HTTPException(status_code=422, detail=f"Failed to create URL record. Invalid data provided.")

        document_id = url_add_result.data[0]["id"]
        task = perform_rag_ingestion.delay(document_id)
        logger.info("url_ingestion_task_queued", document_id=document_id, task_id=task.id, url=url)
        
        doc_update_result = supabase.table("project_documents").update({
            "task_id": task.id
        }).eq("id", document_id).execute()

        if not doc_update_result.data:
            logger.error("url_task_id_update_failed", document_id=document_id, task_id=task.id, reason="no_data_returned")
            raise HTTPException(status_code=422, detail=f"Failed to update URL record with the task id.")

        logger.info("url_processed_successfully", document_id=document_id, url=url, task_id=task.id)
        return {
            "message": "URL added successfully, background processing started.",
            "data": url_add_result.data[0]
        }
    except Exception as e:
        logger.error("url_processing_error", url=url, error=str(e), exc_info=True)
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
    set_project_id(project_id)
    set_user_id(clerk_id)
    try:
        logger.info("deleting_document", file_id=file_id)
        doc_verification_result =  supabase.table("project_documents").select("*").eq("id", file_id).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        if not doc_verification_result:
            logger.warning("document_not_found_for_deletion", file_id=file_id)
            raise HTTPException(status_code=404, detail=f"Document not found / Access denied.")
        
        s3_key = doc_verification_result.data[0]["s3_key"]
        if s3_key:
            logger.info("deleting_from_s3", file_id=file_id, s3_key=s3_key)
            try:
                s3_client.delete_object(Bucket=app_config['s3_bucket_name'], Key=s3_key)
                print("Deleted from S3")

            except Exception as e:
                print("Failed to delete from S3")
                raise HTTPException(status_code=500, detail=f"Failed to delete file from S3 : {str(e)}")
            
        delete_result = supabase.table("project_documents").delete().eq("id", file_id).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        if not delete_result.data:
            logger.error("document_deletion_failed", file_id=file_id, reason="no_data_returned")
            raise HTTPException(status_code=404, detail=f"Document deletion failed.")
        
        logger.info("document_deleted_successfully", file_id=file_id)
        return {
            "message": "File deleted successfully",
            "data": delete_result.data[0]
        }
        
    except Exception as e:
        logger.error("document_deletion_error", file_id=file_id, error=str(e), exc_info=True)
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
    set_project_id(project_id)
    set_user_id(clerk_id)

    try:
        logger.info("fetching_document_chunks", file_id=file_id)
        # See if the document exists and belongs to the user
        doc_verification_result = supabase.table("project_documents").select('id').eq('id', file_id).eq('project_id', project_id).eq("clerk_id", clerk_id).execute()
        if not doc_verification_result.data:
            logger.warning("document_not_found_for_chunks", file_id=file_id)
            raise HTTPException(status_code=404, detail=f"Document not found / Access denied.")
        
        chunks_result = supabase.table("document_chunks").select("*").eq("document_id", file_id).order('chunk_index').execute()
        logger.info("document_chunks_retrieved", file_id=file_id, chunk_count=len(chunks_result.data or []))
        return {
            "message": "Document chunks retrieved successfully",
            "data": chunks_result.data or []
        }
        
    except Exception as e:
        logger.error("document_chunks_retrieval_error", file_id=file_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve document chunks. Reason: {str(e)}")
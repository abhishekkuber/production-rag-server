from src.models.index import ProcessingStatus
from src.services.database import supabase
from src.rag.ingestion.partition import download_and_partition
from src.rag.ingestion.chunking import chunk_elements_by_title
from src.rag.ingestion.summarization import summarise_chunks
from src.rag.ingestion.vectorization import vectorize_and_store_chunks_in_db
from src.config.logging import get_logger, set_project_id

logger = get_logger(__name__)


def get_document(document_id: str):
    doc_result = supabase.table("project_documents").select("*").eq("id", document_id).execute()
    if not doc_result.data:
        logger.error("document_not_found", document_id=document_id)
        raise Exception(f"Failed to get project document record with ID : {document_id}")
    return doc_result.data[0]

def update_document_status_in_db(document_id: str, status: ProcessingStatus, details: dict=None):
    """
        Update the document processing status with optional details in the database.
    """
    logger.info(
        "updating_document_status",
        document_id=document_id,
        status=status.value,
        has_details=details is not None
    )
    try:
        # Get current document
        result = supabase.table("project_documents").select("processing_details").eq("id", document_id).execute()
        if not result.data:
            logger.error(
                "document_not_found",
                document_id=document_id,
                status=status.value
            )
            raise Exception(f"Failed to get project document record with ID : {document_id}.")
        
        current_details = {}
        if result.data and result.data[0]["processing_details"]:
            # Check if there exist any processing details 
            current_details = result.data[0]["processing_details"]

        if details:
            # Merge the current details with the new incoming details
            current_details.update(details)
            logger.debug(
                "merged_processing_details",
                document_id=document_id,
                details_keys=list(details.keys())
            )


        # Update the project document with record with the new details
        update_result = supabase.table("project_documents").update({
            "processing_status": status.value,
            "processing_details": current_details
        }).eq("id", document_id).execute()

        if not update_result.data:
            logger.error(
                "status_update_failed",
                document_id=document_id,
                status=status.value
            )
            raise Exception(f"Failed to update project document record with ID : {document_id}.")
        
        logger.info(
            "document_status_updated_successfully",
            document_id=document_id,
            status=status.value,
            details_count=len(current_details)
        )
    
    except Exception as e:
        logger.error(
            "update_status_error",
            document_id=document_id,
            status=status.value,
            error=str(e),
            exc_info=True
        )
        raise Exception(f"Failed to update status in the database. Reason : {str(e)}")

def process_document(document_id: str):
    '''
    Step 1 : Download the document from S3 (if it is anything other than a url), else crawl the url
    Step 2 : Split the content into chunks
    Step 3 : Generate chunk summaries
    Step 4 : Create chunk embeddings and store in the database.
    '''
    logger.info("document_processing_started", document_id=document_id)
    try:
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.PROCESSING)
        document = get_document(document_id=document_id)
        set_project_id(document["project_id"])
        logger.info("document_retrieved", document_id=document_id, source_type=document.get("source_type"))
        
        # Step 1 : Download the file / scrape based on the document type
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.PARTITIONING)
        elements, elements_summary = download_and_partition(document_id=document_id, document=document)
        logger.info("partitioning_completed", document_id=document_id, elements_summary=elements_summary)

        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.CHUNKING, details={
            ProcessingStatus.PARTITIONING.value: {
                "elements_found": elements_summary
            }
        })

        # Step 2 : Split the content into chunks
        chunks, chunking_metrics = chunk_elements_by_title(elements)
        logger.info("chunking_completed", document_id=document_id, total_chunks=chunking_metrics["total_chunks"])
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.SUMMARISING, details={
            ProcessingStatus.CHUNKING.value: chunking_metrics
        })

        # Step 3 : Generate AI summaries for chunks that h dave tables and images
        processed_chunks = summarise_chunks(chunks, document_id)
        logger.info("summarization_completed", document_id=document_id, chunks_count=len(processed_chunks))
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.VECTORIZATION)

        # Step 4 : Create chunk embeddings and store it in the database
        chunk_ids = vectorize_and_store_chunks_in_db(document_id, processed_chunks)
        logger.info("vectorization_completed", document_id=document_id, stored_chunks=len(chunk_ids))
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.COMPLETED)

        logger.info("document_processing_completed", document_id=document_id, chunks_created=len(processed_chunks))

        return {
            "success": True,
            "document_id": document_id
        }
    
    except Exception as e:
        logger.error("document_processing_failed", document_id=document_id, error=str(e), exc_info=True)
        raise Exception(f"Failed to process document {document_id}. Reason: {str(e)}")
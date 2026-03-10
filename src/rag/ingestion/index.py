from src.models.index import ProcessingStatus
from src.rag.ingestion.partition import download_and_partition
from src.rag.ingestion.chunking import chunk_elements_by_title
from src.rag.ingestion.summarization import summarise_chunks
from src.rag.ingestion.vectorization import vectorize_and_store_chunks_in_db
from src.rag.ingestion.db import update_document_status_in_db, get_document

def process_document(document_id: str):
    '''
    Step 1 : Download the document from S3 (if it is anything other than a url), else crawl the url
    Step 2 : Split the content into chunks
    Step 3 : Generate chunk summaries
    Step 4 : Create chunk embeddings and store in the database.
    '''
    try:
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.PROCESSING)
        document = get_document(document_id=document_id)
        
        # Step 1 : Download the file / scrape based on the document type
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.PARTITIONING)
        elements, elements_summary = download_and_partition(document_id=document_id, document=document)

        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.CHUNKING, details={
            ProcessingStatus.PARTITIONING.value: {
                "elements_found": elements_summary
            }
        })

        # Step 2 : Split the content into chunks
        chunks, chunking_metrics = chunk_elements_by_title(elements)
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.SUMMARISING, details={
            ProcessingStatus.CHUNKING.value: chunking_metrics
        })

        # Step 3 : Generate AI summaries for chunks that h dave tables and images
        processed_chunks = summarise_chunks(chunks, document_id)
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.VECTORIZATION)

        # Step 4 : Create chunk embeddings and store it in the database
        vectorize_and_store_chunks_in_db(document_id, processed_chunks)
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.COMPLETED)

        return {
            "success": True,
            "document_id": document_id
        }
    
    except Exception as e:
        raise Exception(f"Failed to process document {document_id}. Reason: {str(e)}")
    







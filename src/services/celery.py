from celery import Celery
from src.config.index import app_config
from src.rag.ingestion.index import process_document

celery_app = Celery(
    'document_processor', # Name of our Celery app
    broker=app_config['redis_url'], # port that the redis server is listening to ; /0 is the database 
    backend=app_config['redis_url'], # backend where the results of the task will be saved
)

celery_app.conf.update(
    worker_concurrency=4,  # Max 4 parallel document processings
    worker_prefetch_multiplier=1,  # Take 1 task at a time
    task_time_limit=1800,  # Kill tasks after 30 min
    task_soft_time_limit=1500,  # Warn at 25 min
)


@celery_app.task
def perform_rag_ingestion(document_id: str):
    try:
        process_document_result = process_document(document_id)
        return (f"Document {process_document_result[document_id]} processed successfully.")
    except Exception as e:
        return f"Failed to process document {document_id}: {str(e)}"
    

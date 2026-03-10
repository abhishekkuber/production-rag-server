from src.services.database import supabase
from src.models.index import ProcessingStatus


def get_document(document_id: str):
    doc_result = supabase.table("project_documents").select("*").eq("id", document_id).execute()
    if not doc_result.data:
        raise Exception(f"Failed to get project document record with ID : {document_id}")
    return doc_result.data[0]

def update_document_status_in_db(document_id: str, status: ProcessingStatus, details: dict=None):
    """
        Update the document processing status with optional details in the database.
    """
    try:
        # Get current document
        result = supabase.table("project_documents").select("processing_details").eq("id", document_id).execute()
        if not result.data:
            raise Exception(f"Failed to get project document record with ID : {document_id}.")
        
        current_details = {}
        if result.data and result.data[0]["processing_details"]:
            # Check if there exist any processing details 
            current_details = result.data[0]["processing_details"]

        if details:
            # Merge the current details with the new incoming details
            current_details.update(details)


        # Update the project document with record with the new details
        update_result = supabase.table("project_documents").update({
            "processing_status": status.value,
            "processing_details": current_details
        }).eq("id", document_id).execute()

        if not update_result.data:
            raise Exception(f"Failed to update project document record with ID : {document_id}.")
    
    except Exception as e:
        raise Exception(f"Failed to update status in the database. Reason : {str(e)}")
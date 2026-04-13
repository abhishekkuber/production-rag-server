from fastapi import APIRouter, Depends, HTTPException
from src.services.database import supabase
from src.services.auth import get_current_user_clerk_id
from src.models.index import FeedbackRequest
from src.config.logging import get_logger, set_project_id, set_user_id

logger = get_logger(__name__)

router = APIRouter(
    tags=["feedback"],
)


# Create a chat
@router.post("")
async def get_feedback(
    feedback: FeedbackRequest,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    set_user_id(clerk_id)
    set_project_id(feedback.project_id)
    try:
        logger.info("submitting_feedback")
        feedback_result = supabase.table("feedback").insert({
            "rating": feedback.rating,
            "category": feedback.category,
            "comment": feedback.comment,
            "message_id": feedback.message_id,
            "clerk_id": clerk_id
        }).execute() 
        
        if not feedback_result.data:
            logger.error("feedback_submission_failed", reason="no_data_returned")
            raise HTTPException(status_code=422, detail=f"Failed to submit feedback.")
        
        logger.info("feedback_submission_successful")
        return {
            "message": "Feedback submitted successfully",
            "data": feedback_result.data[0]
        }

    except Exception as e:
        logger.error("feedback_submission_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Feedback submission failed. Reason: {str(e)}")
        

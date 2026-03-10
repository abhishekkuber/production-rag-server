from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from enum import Enum


'''
- Field() is a Pydantic function used to provide extra validation constraints and metadata (like descriptions or examples) for model attributes.
- It allows you to define default values while ensuring the field is still recognized by tools like FastAPI for auto-generating OpenAPI documentation.
- ... is the Pydantic standard to say that a field is required
'''

class QueryVariations(BaseModel):
    variations: List[str]=Field(..., description="Query variations generated for Multi Query Search")

class ChatCreate(BaseModel):
    title: str=Field(..., description="The title of the chat")
    project_id: str=Field(..., description="The project ID to which the chat belongs to")

class SendMessageRequest(BaseModel):
    content: str=Field(..., description="The query asked to the LLM")

class FileUploadRequest(BaseModel):
    filename: str=Field(..., description="Name of the file")
    file_size: int=Field(..., description="Size of the file")
    file_type: str=Field(..., description="Type of the file")

class FileConfirmResponse(BaseModel):
    s3_key: str=Field(..., description="The S3 key of the uploaded file")

class UrlAddRequest(BaseModel):
    url: str=Field(..., description="The URL to process")
    
class ProjectCreate(BaseModel):
    name: str=Field(..., description="The name of the project")
    description: Optional[str]=Field(None, description="Project description")

class ProjectSettings(BaseModel):
    embedding_model: str=Field(..., description="The embedding model to use")
    rag_strategy: str=Field(..., description="The RAG search strategy to use")
    agent_type: str=Field(..., description="The agent type to use")
    chunks_per_search: int=Field(..., description="Number of chunks returned per search")
    final_context_size: int=Field(..., description="Final context size to be used for answer generation")
    similarity_threshold: float=Field(..., description="Similarity threshold for vector search")
    number_of_queries: int=Field(..., description="Number of queries to be generated in Multi-Query search")
    reranking_enabled: bool=Field(..., description="Whether reranking is enabled")
    reranking_model: str=Field(..., description="The reranking model to use")
    vector_weight: float=Field(..., description="Weight given to vector search")
    keyword_weight: float=Field(..., description="Weight given to keyword search")

class MessageRole(str, Enum):
    USER="user"
    ASSISTANT="assistant"


class ProcessingStatus(str, Enum):
    UPLOADING = "uploading"
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    PARTITIONING = "partitioning"
    CHUNKING = "chunking"
    SUMMARISING = "summarising"
    VECTORIZATION = "vectorization"
    COMPLETED = "completed"

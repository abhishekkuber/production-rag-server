from fastapi import APIRouter, Depends, HTTPException
from database import supabase 
from pydantic import BaseModel
from auth import get_current_user
from typing import List, Tuple, Dict
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_huggingface import HuggingFaceEmbeddings, ChatHuggingFace
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_huggingface.llms import HuggingFaceEndpoint

router = APIRouter(
    tags=["chats"]
)

class QueryVariations(BaseModel):
    variations: List[str]

'''
hf_endpoint = HuggingFaceEndpoint(
                # You have to make sure that this model has an InferenceProvider on the HuggingFace Website.
                # model="CohereLabs/aya-vision-32b", 
                # model="meta-llama/Llama-3.1-8B-Instruct", 
                model="google/gemma-3-27b-it", 
                task="conversational",
                temperature=0,
                provider="auto"
            )

llm = ChatHuggingFace(llm=hf_endpoint)
# Make sure that this is the same embedding model used to embed document chunks
embedding_model = HuggingFaceEmbeddings(model="intfloat/e5-large-v2")
'''

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
embedding_model = OpenAIEmbeddings(model="text-embedding-3-large", dimensions=1536)


class ChatCreate(BaseModel):
    title: str
    project_id: str

class SendMessageRequest(BaseModel):
    content: str

def validate_context(texts: List[str], images: List[str], tables: List[str], citations: List[Dict]) -> None:
    """Validate and print context data in a readable format"""
    print("\n" + "="*80)
    print("📦 CONTEXT VALIDATION")
    print("="*80)
    
    # Texts - SHOW FULL TEXT
    print(f"\n📝 TEXTS: {len(texts)} chunks")
    for i, text in enumerate(texts, 1):
        print(f"\n{'='*80}")
        print(f"CHUNK [{i}] - {len(text)} characters")
        print(f"{'='*80}")
        print(text)  # ✅ Full text, no truncation
        print(f"{'='*80}\n")
    
    # Images
    print(f"\n🖼️  IMAGES: {len(images)}")
    for i, img in enumerate(images, 1):
        img_preview = str(img)[:60] + ('...' if len(str(img)) > 60 else '')
        print(f"  [{i}] {img_preview}")
    
    # Tables
    print(f"\n📊 TABLES: {len(tables)}")
    for i, table in enumerate(tables, 1):
        if isinstance(table, dict):
            rows = len(table.get('rows', []))
            cols = len(table.get('headers', []))
            print(f"  [{i}] {rows} rows × {cols} cols")
        else:
            print(f"  [{i}] Type: {type(table).__name__}")
    
    # Citations
    print(f"\n📚 CITATIONS: {len(citations)}")
    for i, cite in enumerate(citations, 1):
        chunk_id = cite['chunk_id'][:8] if cite.get('chunk_id') else 'N/A'
        print(f"  [{i}] {cite['filename']} (pg.{cite['page']}) | chunk: {chunk_id}...")
    
    # Summary
    total_chars = sum(len(text) for text in texts)
    print(f"\n{'='*80}")
    print(f"✅ Total: {len(texts)} texts ({total_chars:,} chars), {len(images)} images, {len(tables)} tables, {len(citations)} citations")
    print("="*80 + "\n")


# We accept the parameters as lists because down the line if we decide to add a
# type of search to our app, this can be easily extended (for ex: multi query search)
def reciprocal_rank_fusion(search_results_list: List[List[Dict]], weights: List[float]=None, k: int=60):
    """
        Do the Reciprocal Rank Fusion and return the new ranked list
    """

    # not search_results_list : Check whether the outer list is empty / falsy / null 
    # not any(search_results_list) : Check whether all the inner lists are empty.
    if not search_results_list or not any(search_results_list):
        return []
    
    if weights is None:
        # basically weights = [0.5, 0.5]
        weights = [1.0 / len(search_results_list)] * len(search_results_list)

    chunk_scores = {}
    all_chunks = {}

    for search_idx, results in enumerate(search_results_list):
        search_weight = weights[search_idx]

        for rank, chunk in enumerate(results):
            chunk_id = chunk.get('id')
            if not chunk_id:
                continue

            rrf_score = search_weight * (1.0 / (rank + 1 + k))
            if chunk_id in chunk_scores:
                chunk_scores[chunk_id] += rrf_score
            else:
                chunk_scores[chunk_id] = rrf_score
                all_chunks[chunk_id] = chunk
    
    # Sort and get the list of chunk ids based on their scores
    sorted_chunk_ids = sorted(chunk_scores.keys(), key=lambda chunk_id: chunk_scores[chunk_id], reverse=True)
    return [all_chunks[chunk_id] for chunk_id in sorted_chunk_ids]


def build_context(chunks: List[Dict]) -> Tuple[List[str], List[str], List[str], List[Dict]]:
    """
        Returns tuple of (texts, images, tables, citations)
        We are just trying to extract the components and separate them from each chunk.
    """
    if not chunks:
        return ([], [], [], [])
    
    texts = []
    images = []
    tables = []
    citations = []

    # Get the doc_ids of the relevant chunks
    doc_ids = [chunk['document_id'] for chunk in chunks if chunk.get('document_id')]
    # Since there can be multiple chunks from the same document, we only keep the unique values
    unique_doc_ids: List[str] = list(set(doc_ids))

    filename_map = {}

    if unique_doc_ids:
        # Select the ids and filenames of the documents whose ids are in the unique_doc_ids
        result = supabase.table('project_documents').select('id', 'filename').in_('id', unique_doc_ids).execute()
        filename_map = {doc['id']: doc['filename'] for doc in result.data}
    
    for chunk in chunks:
        original_content = chunk.get('original_content', {})

        chunk_text = original_content.get('text', '')
        chunk_images = original_content.get('images', [])
        chunk_tables = original_content.get('tables', [])

        if chunk_text:
            texts.append(chunk_text)
        images.extend(chunk_images)
        tables.extend(chunk_tables)

        # Add citation for each chunk
        doc_id = chunk.get('document_id')
        if doc_id:
            citations.append({
                "chunk_id": chunk.get("id"), 
                "document_id": doc_id,
                "filename": filename_map.get(doc_id, "Unknown Document"),
                "page": chunk.get("page_number", "Unknown")
            })
        
    return texts, images, tables, citations

def vector_search(message, document_ids, project_settings):
    query_embedding = embedding_model.embed_query(message)
    vector_search_results = supabase.rpc(
        fn="vector_search_document_chunks",
        params= {
            "query_embedding": query_embedding,
            "filter_document_ids": document_ids,
            "match_threshold": project_settings['similarity_threshold'],
            "chunks_per_search": project_settings['chunks_per_search'],
        }
    ).execute()

    return vector_search_results.data if vector_search_results.data else []

def keyword_search(message, document_ids, project_settings):
    keyword_search_results = supabase.rpc(
        fn="keyword_search_document_chunks",
        params={
            "query_text":message,
            "filter_document_ids": document_ids,
            "chunks_per_search": project_settings['chunks_per_search']
        }
    ).execute()
    return keyword_search_results.data if keyword_search_results.data else []


def hybrid_search(message, document_ids, project_settings):
    vector_search_chunks = vector_search(message, document_ids, project_settings)
    keyword_search_chunks = keyword_search(message, document_ids, project_settings)

    # Combine using Reciprocal Rank Fusion
    return reciprocal_rank_fusion(
        [vector_search_chunks, keyword_search_chunks],
        [project_settings['vector_weight'], project_settings['keyword_weight']]
    )

def generate_query_variations(message: str,  num_queries: int=3) -> List[str]:
    """
        Take the original query and make multiple variations of it. Used in multi query search strategies.
    """
    system_prompt = f"""Generate {num_queries-1} alternative ways to phrase this questions for document search. Use different keywords and synonyms while maintaining the same intent. Return exactly {num_queries-1} variations."""

    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Original query: {message}")
        ]
        structured_llm = llm.with_structured_output(QueryVariations)
        result = structured_llm.invoke(messages)
        return [message] + result.variations[:num_queries-1]
    
    except Exception as e:
        print(f"Cannot generate query variations. Reason : {str(e)}")
        return [message]

def prepare_prompt_and_invoke_llm(user_query:str, texts:List[str], images:List[str], tables:List[str]) -> str:
    """
        Builds system prompt with context and invokes LLM with multi-modal support

        Args: 
            user_query: The question that the user asks
            texts: List of text contents of the most relevant chunks
            images: List of images in the most relevant chunks, as base64 strings
            tables: List of tables in the most relevant chunks
        
        Returns: 
            The LLM response as a string
    """
    prompt_parts = []

    # We are going to have one system message and one human message.
    # In the system message, we are put in all the context. 
    # Ideally, we would also provide the images in the system prompt. 
    # Unfortunately, we cannot put base64 in the system prompts.
    # SystemMessage -> Context (Text + Tables) + Instructions
    # HumanMessage -> Images + User query  
    prompt_parts = []
    
    # Main instruction
    prompt_parts.append(
        "You are a helpful AI assistant that answers questions based solely on the provided context. "
        "Your task is to provide accurate, detailed answers using ONLY the information available in the context below.\n\n"
        "IMPORTANT RULES:\n"
        "- Only answer based on the provided context (texts, tables, and images)\n"
        "- If the answer cannot be found in the context, respond with: 'I don't have enough information in the provided context to answer that question.'\n"
        "- Do not use external knowledge or make assumptions beyond what's explicitly stated\n"
        "- When referencing information, be specific and cite relevant parts of the context\n"
        "- Synthesize information from texts, tables, and images to provide comprehensive answers\n\n"
    )

    # Add text contexts
    if texts:
        prompt_parts.append("=" * 80)
        prompt_parts.append("CONTEXT DOCUMENTS")
        prompt_parts.append("=" * 80 + "\n")
        
        for i, text in enumerate(texts, 1):
            prompt_parts.append(f"--- Document Chunk {i} ---")
            prompt_parts.append(text.strip())
            prompt_parts.append("")
    
    # Add tables if present
    if tables:
        prompt_parts.append("\n" + "=" * 80)
        prompt_parts.append("RELATED TABLES")
        prompt_parts.append("=" * 80)
        prompt_parts.append(
            "The following tables contain structured data that may be relevant to your answer. "
            "Analyze the table contents carefully.\n"
        )
        
        for i, table_html in enumerate(tables, 1):
            prompt_parts.append(f"--- Table {i} ---")
            prompt_parts.append(table_html)
            prompt_parts.append("")
    
    # Reference images if present
    if images:
        prompt_parts.append("\n" + "=" * 80)
        prompt_parts.append("RELATED IMAGES")
        prompt_parts.append("=" * 80)
        prompt_parts.append(
            f"{len(images)} image(s) will be provided alongside the user's question. "
            "These images may contain diagrams, charts, figures, formulas, or other visual information. "
            "Carefully analyze the visual content when formulating your response. "
            "The images are part of the retrieved context and should be used to answer the question.\n"
        )
    
    # Final instruction
    prompt_parts.append("=" * 80)
    prompt_parts.append(
        "Based on all the context provided above (documents, tables, and images), "
        "please answer the user's question accurately and comprehensively."
    )
    prompt_parts.append("=" * 80)
    
    system_prompt = "\n".join(prompt_parts)
    
    # Build messages for LLM
    messages = [SystemMessage(content=system_prompt)]
    
    # Create human message with user query and images
    if images:
        # Multi-modal message: text + images
        content_parts = [{"type": "text", "text": user_query}]
        
        # Add each image to the content array
        for img_base64 in images:
            # Clean base64 string if it has data URI prefix
            if img_base64.startswith('data:image'):
                img_base64 = img_base64.split(',', 1)[1]
            
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}
            })
        
        messages.append(HumanMessage(content=content_parts))
    else:
        # Text-only message
        messages.append(HumanMessage(content=user_query))
    
    response = llm.invoke(messages)
    return response.content


# Create a chat
@router.post("/api/chats")
async def create_chat(
    chat: ChatCreate,
    clerk_id: str=Depends(get_current_user)
):
    try:
        created_chat = supabase.table("chats").insert({
            "title": chat.title,
            "project_id": chat.project_id,
            "clerk_id": clerk_id
        }).execute()

        return {
            "message": "Chat created successfully",
            "data": created_chat.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create chat : {str(e)}")
    
# Delete a chat
@router.delete("/api/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        delete_result = supabase.table("chats").delete().eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if not delete_result:
            raise HTTPException(status_code=404, detail=f"Chat deletion failed : {str(e)}")
        
        return {
            "message": "Chat deleted successfully",
            "data": delete_result.data[0]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete chat : {str(e)}")
    

# Get the messages of the chat
@router.get("/api/chats/{chat_id}")
async def get_chat(
    chat_id: str,
    clerk_id: str=Depends(get_current_user)
):
    try:
        # Get the chat and verify it belongs to the user AND has a project id
        result = supabase.table("chats").select("*").eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if not result.data[0]:
            raise HTTPException(status_code=404, detail=f"Chat not found / Access denied : {str(e)}")
        
        chat = result.data[0]
        # Get all the messages for this chat
        messages_result = supabase.table("messages").select("*").eq("chat_id", chat_id).eq("clerk_id", clerk_id).order('created_at', desc=False).execute()
        chat['messages'] = messages_result.data or []

        return {
            "message": "Chat retrieved successfully",
            "data": chat
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat : {str(e)}")


# Send a message and get the corresponding LLM response
@router.post("/api/projects/{project_id}/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    project_id: str,
    request: SendMessageRequest,
    clerk_id: str=Depends(get_current_user)
):
    try:
        message = request.content
        print(f"Saving user message")
        user_message = supabase.table("messages").insert({
            "content": message,
            "role": "user",
            "chat_id": chat_id,
            "clerk_id": clerk_id,
        }).execute()
        print(f"User message saved")

        # Step 2 : Load project settings
        project_settings = supabase.table("project_settings").select("*").eq("project_id", project_id).execute()
        if not project_settings.data:
            raise HTTPException(status_code=404, detail=f"Project settings not found / Access denied : {str(e)}")
        project_settings = project_settings.data[0]

        # Step 3 : Get the document IDs for this project
        document_ids = supabase.table("project_documents").select("id").eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        if not document_ids.data:
            raise HTTPException(status_code=404, detail=f"No documents found / Access denied : {str(e)}")
        document_ids = [doc['id'] for doc in document_ids.data]

        # Extract the type of the search strategy to be used
        search_strategy = project_settings['rag_strategy']
        
        if search_strategy == "basic":
            chunks = vector_search(message, document_ids, project_settings)
        elif search_strategy == "hybrid":
            chunks = hybrid_search(message, document_ids, project_settings)
        elif search_strategy == "multi-query-vector":
            queries = generate_query_variations(message, project_settings['number_of_queries'])
            all_results = []
            for i, query in enumerate(queries):
                results = vector_search(query, document_ids, project_settings)
                print(f"Query {i+1}: {query}\nReturned {len(results)} chunks\n\n")
                all_results.append(results)
            chunks = reciprocal_rank_fusion(all_results)
        elif search_strategy == "multi-query-hybrid":
            print("DOING MULTI QUERY HYBRID SEARCH")
            queries = generate_query_variations(message, project_settings['number_of_queries'])
            all_results = []
            for i, query in enumerate(queries):
                results = hybrid_search(message, document_ids, project_settings)
                all_results.append(results)
            chunks = reciprocal_rank_fusion(all_results)

        chunks = chunks[:project_settings['final_context_size']]
        # Step 6 : Build context from the retrieved chunks
        texts, images, tables, citations = build_context(chunks)
        validate_context(texts, images, tables, citations)

        # Step 7 : Build system prompt with injected context
        ai_response = prepare_prompt_and_invoke_llm(
            user_query=message,
            texts=texts,
            images=images,
            tables=tables,
        )


        print(f"Saving AI message")
        ai_message = supabase.table("messages").insert({
            "content": ai_response,
            "role": "assistant",
            "chat_id": chat_id,
            "clerk_id": clerk_id,
            "citations": citations
        }).execute()
        print(f"AI message saved")
        
        return {
            "message": "Messages sent successfully",
            "data": {
                "userMessage": user_message.data[0],
                "aiMessage": ai_message.data[0]
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")
    

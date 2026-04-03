from src.services.llm import open_ai_models
from src.services.database import supabase

def vectorize_and_store_chunks_in_db(document_id, processed_chunks):
    """
        Generate embeddings and store chunks in one efficient operation
    """
    from src.rag.ingestion.index import logger  

    if not processed_chunks:
        print("No chunks to process")
        return []
    
    texts = [chunk['content'] for chunk in processed_chunks]
    
    # Generate embeddings in batches to avoid API limits
    batch_size = 10
    all_embeddings = []
    logger.info("vectorization_started", document_id=document_id, total_chunks=len(processed_chunks), batch_size=batch_size)
    for i in range(0, len(texts), batch_size): 
        batch_texts = texts[i:i+batch_size]
        batch_embeddings = open_ai_models["embedding_model"].embed_documents(batch_texts)
        all_embeddings.extend(batch_embeddings)

    stored_chunk_ids = []

    for i, (chunk, embedding) in enumerate(zip(processed_chunks, all_embeddings)):
        chunk_data_with_embedding = {
            **chunk,
            'document_id': document_id,
            'chunk_index': i,
            'embedding': embedding
        }
        
        try:
            result = supabase.table('document_chunks').insert(chunk_data_with_embedding).execute()
            stored_chunk_ids.append(result.data[0]['id'])
        except Exception as e:
            print(f"Cannot add to table: {str(e)}")
    
    print(f"Successfully stored {len(stored_chunk_ids)} chunks with embeddings")
    return stored_chunk_ids
    
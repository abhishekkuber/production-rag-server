from unstructured.chunking.title import chunk_by_title

def chunk_elements_by_title(elements):
    chunks = chunk_by_title(
        elements=elements,
        max_characters=3000, # Hard limit - never exceed 3000 characters per chunk
        new_after_n_chars= 2400, # Try to start a new chunk after 2400 characters 
        combine_text_under_n_chars= 500, # merge tiny chunks under 500 chars with neighbours
    )

    # Collect chunking metrics
    total_chunks = len(chunks)
    chunking_metrics = {
        "total_chunks": total_chunks
    }
    return chunks, chunking_metrics

from typing import List, Dict, Tuple
from src.services.database import supabase
from src.rag.retrieval.db import get_document_filenames

def separate_content_types(chunks: List[Dict]) -> Tuple[List[str], List[str], List[str], List[Dict]]:
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
        filename_map = get_document_filenames(unique_doc_ids)
    
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

    # _validate_context(texts, images, tables, citations)
    return texts, images, tables, citations


def _validate_context(texts: List[str], images: List[str], tables: List[str], citations: List[Dict]) -> None:
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

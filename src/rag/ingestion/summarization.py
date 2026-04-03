from src.models.index import ProcessingStatus
from src.services.llm import open_ai_models
from langchain_core.messages import HumanMessage

def summarise_chunks(chunks, document_id):
    """Process all chunks with AI summaries"""
    # Local import avoids circular import during module initialization.
    from src.rag.ingestion.index import update_document_status_in_db

    processed_chunks = []
    total_chunks = len(chunks)

    for i, chunk in enumerate(chunks):
        # Update progress directly
        update_document_status_in_db(document_id=document_id, status=ProcessingStatus.SUMMARISING, details={
            ProcessingStatus.SUMMARISING.value: {
                "current_chunk": i+1,
                "total_chunks": total_chunks
            }
        })


        content_data = separate_content_data(chunk)

        # Use LLMs to summarise the chunks if they contain atleast one table or image.
        if content_data['images'] or content_data['tables']:
            try:
                enhanced_content = create_ai_enhanced_summary(content_data['text'], content_data['images'], content_data['tables'])
            except Exception as e:
                print(f"AI Summary Failed : {e}")
                enhanced_content = content_data['text']
        else:
            enhanced_content = content_data['text']
        

        original_content = {
            'text': content_data["text"]
        }

        if content_data["tables"]:
            original_content["tables"] = content_data["tables"]
        
        if content_data["images"]:
            original_content["images"] = content_data["images"]

        processed_chunk = {
            'content': enhanced_content,
            'original_content': original_content,
            'type': content_data['types'],
            'page_number': get_page_number(chunk, i),
            'char_count': len(enhanced_content)
        }

        processed_chunks.append(processed_chunk)
    
    return processed_chunks


def separate_content_data(chunk, source_type="file"):
    """
        Analyze what types of content are in a chunk. Separate them into 'buckets' and return them
    """
    is_url_source = source_type == "url"
    content_data = {
        'text': chunk.text,
        'images': [],
        'tables': [],
        'types' : ['text']
    }

    if hasattr(chunk, 'metadata') and hasattr(chunk.metadata, 'orig_elements'):
        for element in chunk.metadata.orig_elements:
            element_type = type(element).__name__

            if element_type == "Table":
                table_html = getattr(element.metadata, "text_as_html", element.text)
                content_data['tables'].append(table_html)
                content_data['types'].append('table')
                
            if element_type == "Image" and not is_url_source:
                if (hasattr(element, "metadata") and hasattr(element.metadata, "image_base64") and element.metadata.image_base64 is not None):    
                    content_data['images'].append(element.metadata.image_base64)
                    content_data['types'].append('image')
            
    content_data['types'] = list(set(content_data['types']))
    return content_data


def get_page_number(chunk, chunk_idx):
    """
        Get page number from chunk metadata or use fallback
    """
    if hasattr(chunk, 'metadata'):
        page_number = getattr(chunk.metadata, 'page_number', None)
        if page_number is not None:
            return page_number
    return chunk_idx+1


def create_ai_enhanced_summary(text, images, tables):
    """
        Create an AI enhanced summary for chunks containing images and tables
    """
    try:
        # Base prompt text
        prompt_text = f"""Create a searchable index for this document content.
        CONTENT TO ANALYZE:
        TEXT CONTENT:
        {text}
        """

        if tables:
            prompt_text += "TABLES:\n"
            for i, table in enumerate(tables):
                prompt_text += f"Table {i+1}:\n{table}\n\n"
            prompt_text += """
            YOUR TASK:
            Generate a structured search index (aim for 250-400) words:

            QUESTIONS: List 5-7 key questions this content answers (use what/how/why/when/who variations)

            KEYWORDS: Include: 
            - Specific data (numbers, dates, percentages, amounts)
            - Core concepts and themes 
            - Technical terms and casual alternatives
            - Industry terminology

            VISUALS (if images present):
            - Chart/graph types and what they show
            - Trends and patterns visible
            - Key insights from visualizations

            DATA RELATIONSHIPS (if tables present):
            - Column headers and their meaning
            - Key metrics and relationships
            - Notable values or patterns

            Focus on terms users would actually search for. Be specific and comprehensive.
            
            SEARCH INDEX:
            """
        
        message_content = [{"type": "text", "text": prompt_text}]

        if images:
            for image in images:
                message_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image}"}
                })

        message = HumanMessage(content=message_content)
        response = open_ai_models["summary_llm"].invoke([message])

        return response.content

    except Exception as e:
        raise Exception(f"Failed to create AI summary. Reason: {str(e)}")
    
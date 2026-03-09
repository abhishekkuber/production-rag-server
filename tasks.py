import os
import json

from typing import List
from celery import Celery
from database import supabase, s3_client, BUCKET_NAME
from unstructured.partition.pdf import partition_pdf 
from unstructured.partition.docx import partition_docx
from unstructured.partition.md import partition_md
from unstructured.partition.pptx import partition_pptx
from unstructured.partition.text import partition_text
from unstructured.partition.html import partition_html
from unstructured.chunking.title import chunk_by_title
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage 
from langchain_huggingface import HuggingFaceEmbeddings, ChatHuggingFace
from langchain_huggingface.llms import HuggingFaceEndpoint
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from scrapingbee import ScrapingBeeClient

scrapingbee_client = ScrapingBeeClient(api_key=os.getenv('SCRAPINGBEE_API_KEY'))

'''
hf_endpoint = HuggingFaceEndpoint(
                model="CohereLabs/aya-vision-32b", # you have to make sure that this model has an InferenceProvider on the HuggingFace Website.
                task="conversational",
                temperature=0,
                provider="auto"
            )
llm = ChatHuggingFace(llm=hf_endpoint)

embedding_model = HuggingFaceEmbeddings(model="intfloat/e5-large-v2")
'''

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
embedding_model = OpenAIEmbeddings(model="text-embedding-3-large", dimensions=1536)

# Create Celery app
celery_app = Celery(
    'document_processor', # Name of our Celery app
    broker="redis://localhost:6379/0", # port that the redis server is listening to ; /0 is the database 
    backend="redis://localhost:6379/0" # backend where the results of the task will be saved
)

celery_app.conf.update(
    worker_concurrency=4,  # Max 4 parallel document processings
    worker_prefetch_multiplier=1,  # Take 1 task at a time
    task_time_limit=1800,  # Kill tasks after 30 min
    task_soft_time_limit=1500,  # Warn at 25 min
)

'''
If you have many tasks with a long duration you want the multiplier
value to be one: meaning it’ll only reserve one task per worker
process at a time.

However – If you have many short-running tasks, and 
throughput/round trip latency is important to you, 
this number should be large. The worker is able to process 
more tasks per second if the messages have already been
prefetched, and is available in memory. You may have to  
experiment to find the best value that works for you.
Values like 50 or 150 might make sense in these circumstances.
Say 64, or 128.
'''

@celery_app.task
def process_document(document_id: str):
    """
        Real document processing
    """
    try:
        doc_result = supabase.table("project_documents").select("*").eq("id", document_id).execute()
        document = doc_result.data[0]
        source_type = document.get('source_type', 'file')
        
        # Step 1 : Download the file from S3 and partition
        update_status(document_id, "partitioning")
        elements = download_and_partition(document_id, document)

        # Step 2 : Chunk elements
        chunks, chunking_metrics = chunk_elements_by_title(elements)
        update_status(document_id, "summarising", {
            "chunking": chunking_metrics
        })

        # Step 3 : Summarise chunks
        processed_chunks = summarise_chunks(chunks, document_id, source_type)

        # Step 4 : Vectorization and storing
        # You vectorize the enhanced content
        update_status(document_id, "vectorization")
        stored_chunk_ids = store_chunks_with_embeddings(document_id, processed_chunks)

        update_status(document_id, "completed")
        print(f"Celery task completed. Stored document {document_id}, with {len(stored_chunk_ids)} chunks")
        
        
        return {
            "message": "success",
            "document_id": document_id
        }
    
    except Exception as e:
        pass


def download_and_partition(document_id: str, document: dict): 
    """
        Download the document from S3.
        If the document is a URL, then crawl it.
        Finally, partition into elements
    """
    print(f"Downloading and partitioning document : {document_id}")
    source_type = document.get("source_type", "file")

    if source_type == "url":
        # Crawl the URL
        url = document["source_url"]

        # Fetch the content with ScrapingBee
        response = scrapingbee_client.get(url)

        # Save to temp file
        temp_file = f"/tmp/{document_id}.html"
        with open(temp_file, 'wb') as f:
            f.write(response.content)
        
        elements = partition_document(temp_file, "html", source_type="url")

    else:
        # Handle file processing
        s3_key = document["s3_key"]
        filename = document["filename"]
        file_type = filename.split(".")[-1].lower()

        # Download to a temporary location
        temp_file = f"/tmp/{document_id}.{file_type}"
        s3_client.download_file(BUCKET_NAME, s3_key, temp_file)

        elements = partition_document(temp_file, file_type, source_type="file")

    elements_summary = analyze_elements(elements)
    update_status(document_id, "chunking", {
        "partitioning": {
            "elements_found": elements_summary
        }
    })

    # After partitioning is done, delete the downloaded file
    os.remove(temp_file)

    return elements


def partition_document(temp_file: str, file_type: str, source_type: str="file"):
    """
        Partition documents based on file type and source type
    """
    if source_type == "url":
        return partition_html(
            filename=temp_file
        )
    elif file_type == "pdf":
        return partition_pdf(
            filename=temp_file,  # Path to your PDF file
            strategy="hi_res", # Use the most accurate (but slower) processing method of extraction
            infer_table_structure=True, # Keep tables as structured `HTML`, not jumbled text
            extract_image_block_types=["Image"], # Grab images found in the PDF
            extract_image_block_to_payload=True # Store images as base64 data you can actually use
        )
    elif file_type == "docx":
        return partition_docx(
            filename=temp_file,
            strategy="hi_res",
            infer_table_structure=True
        )
    elif file_type == "pptx":
        return partition_pptx(
            filename=temp_file,
            strategy="hi_res",
            infer_table_structure=True
        )
    elif file_type == "txt":
        return partition_text(
            filename=temp_file,
        )
    elif file_type == "md":
        return partition_md(
            filename=temp_file,
        )


def analyze_elements(elements):
    """
        Count different types of elements found in the document
    """
    text_count = 0
    table_count = 0
    image_count = 0
    title_count = 0
    other_count = 0

    # Go through each element and count what type it is 
    for elem in elements:
        element_name = type(elem).__name__ # Get the class name like Table or NarrativeText
        if element_name == "Table":
            table_count += 1
        elif element_name == "Image":
            image_count += 1
        elif element_name in ["Title", "Header"]:
            title_count += 1
        elif element_name in ["NarrativeText", "Text", "ListItem", "FigureCaption"]:
            text_count += 1
        else:
            other_count += 1

    return {
        "text": text_count,
        "tables": table_count,
        "images": image_count,
        "titles": title_count,
        "other": other_count
    }


def update_status(document_id: str, status: str, details: dict=None):
    """
        Update the document processing status with optional details
    """
    # Get current document
    result = supabase.table("project_documents").select("processing_details").eq("id", document_id).execute()
    current_details = {}

    if result.data and result.data[0]["processing_details"]:
        current_details = result.data[0]["processing_details"]

    if details:
        # Merge the current details with the new incoming details
        current_details.update(details)


    supabase.table("project_documents").update({
        "processing_status": status,
        "processing_details": current_details
    }).eq("id", document_id).execute()


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

def create_ai_enhanced_summary(text, images, tables):
    """
        Create an AI enhanced summary for multimodal content
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
        response = llm.invoke([message])
        
        return response.content

    except Exception as e:
        print(f"AI Summary Failed BECAUSE {e}") 
        summary = f"{text[:300]}..."
        return summary

def separate_content_types(chunk, source_type="file"):
    """
        Analyze what types of content are in a chunk
    """
    is_url_source = source_type == "url"
    content_types = {
        'text': chunk.text,
        'images': [],
        'tables': [],
        'types' : ['text']
    }


    if hasattr(chunk, 'metadata') and hasattr(chunk.metadata, 'orig_elements'):
        for element in chunk.metadata.orig_elements:
            element_type = type(element).__name__

            if element_type == "Table":
                table_html = getattr(element.metadata, "text_as_html")
                content_types['tables'].append(table_html)
                content_types['types'].append('table')
                
            if element_type == "Image":
                image_base64 = getattr(element.metadata, "image_base64")
                content_types['images'].append(image_base64)
                content_types['types'].append('image')
            
    content_types['types'] = list(set(content_types['types']))
    return content_types

def get_page_number(chunk, chunk_idx):
    """
        Get page number from chunk metadata or use fallback
    """
    if hasattr(chunk, 'metadata'):
        page_number = getattr(chunk.metadata, 'page_number', None)
        if page_number is not None:
            return page_number
    return chunk_idx+1

def summarise_chunks(chunks, document_id, source_type):
    """Process all chunks with AI summaries"""
    processed_chunks = []
    total_chunks = len(chunks)

    for i, chunk in enumerate(chunks):
        # Update progress directly
        update_status(document_id, "summarising", {
            "summarising": {
                "current_chunk": i+1,
                "total_chunks": total_chunks
            }
        })

        content_data = separate_content_types(chunk)
        if content_data['images'] or content_data['tables']:
            # print(f"Creating AI summary for chunk {i+1}.")
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
        

def store_chunks_with_embeddings(document_id, processed_chunks):
    """
        Generate embeddings and store chunks in one efficient operation
    """

    if not processed_chunks:
        print("No chunks to process")
        return []
    
    texts = [chunk['content'] for chunk in processed_chunks]
    
    # Generate embeddings in batches to avoid API limits
    batch_size = 10
    all_embeddings = []
    for i in range(0, len(texts), batch_size): 
        batch_texts = texts[i:i+batch_size]
        batch_embeddings = embedding_model.embed_documents(batch_texts)
        all_embeddings.extend(batch_embeddings)


    stored_chunk_ids = []

    for i, (chunk, embedding) in enumerate(zip(processed_chunks, all_embeddings)):
        chunk_data_with_embedding = {
            **chunk,
            'document_id': document_id,
            'chunk_index': i,
            'embedding': embedding
        }
        
        '''
        print(f"CHUNK {i+1}")
        result = supabase.table('document_chunks').insert(chunk_data_with_embedding).execute()
        stored_chunk_ids.append(result.data[0].id)
        '''
        
        try:
            result = supabase.table('document_chunks').insert(chunk_data_with_embedding).execute()
            stored_chunk_ids.append(result.data[0]['id'])
        except Exception as e:
            print(f"Cannot add to table: {str(e)}")
    
    print(f"Successfully stored {len(stored_chunk_ids)} chunks with embeddings")
    return stored_chunk_ids
    
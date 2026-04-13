from unstructured.partition.pdf import partition_pdf 
from unstructured.partition.docx import partition_docx
from unstructured.partition.md import partition_md
from unstructured.partition.pptx import partition_pptx
from unstructured.partition.text import partition_text
from unstructured.partition.html import partition_html
from unstructured.chunking.title import chunk_by_title

from src.services.web_scraper import scrapingbee_client
from src.config.index import app_config
from src.services.aws_s3 import s3_client

import os

def download_and_partition(document_id: str, document: dict): 
    """
        The content type can be a URL or a file.
            - If it is a file, download it from S3.
            - If it is a URL, then crawl and scrape it.
        Finally, partition into elements, analyze and upload to db.
    """
    from src.rag.ingestion.index import logger  
    try:
        document_type = document["source_type"]
        elements = None
        temp_file_path = None

        if document_type == "url":
            # Crawl the URL
            url = document["source_url"]

            logger.info("crawling_url", document_id=document_id, url=url)
            # Fetch the content with ScrapingBee
            response = scrapingbee_client.get(url)

            # Save to temp file
            temp_file_path = f"/tmp/{document_id}.html"
            with open(temp_file_path, 'wb') as f:
                f.write(response.content)

            logger.info("url_crawl_completed", document_id=document_id)
             
            elements = partition_document(temp_file_path, "html", source_type="url")

        else:
            # Handle file processing
            s3_key = document["s3_key"]
            filename = document["filename"]
            file_type = filename.split(".")[-1].lower()

            # Download to a temporary location
            temp_file_path = f"/tmp/{document_id}.{file_type}"
            logger.info("downloading_from_s3", document_id=document_id, s3_key=s3_key, file_type=file_type)
            s3_client.download_file(app_config['s3_bucket_name'], s3_key, temp_file_path)
            logger.info("s3_download_completed", document_id=document_id)

            elements = partition_document(temp_file_path, file_type, source_type="file")

        elements_summary = analyze_elements(elements)
        logger.info("elements_analyzed", document_id=document_id, elements_count=len(elements))
        

        # After partitioning is done, delete the temporary downloaded file
        os.remove(temp_file_path)

        return elements, elements_summary
    
    except Exception as e:
        logger.error("download_and_partition_failed", document_id=document_id, error=str(e), exc_info=True)
        raise Exception(f"Failed to download the document content and partition. Reason : {str(e)}")


def partition_document(temp_file_path: str, file_type: str, source_type: str="file"):
    """
        Partition documents based on file type and source type.
    """
    source_type = (source_type or "file").lower()
    file_type = file_type.lower()
    
    if source_type == "url":
        return partition_html(
            filename=temp_file_path
        )
    
    supported_file_types = {
        "pdf": lambda: partition_pdf(
            filename=temp_file_path,  # Path to your PDF file
            strategy="hi_res", # Use the most accurate (but slower) processing method of extraction
            infer_table_structure=True, # Keep tables as structured `HTML`, not jumbled text
            extract_image_block_types=["Image"], # Grab images found in the PDF
            extract_image_block_to_payload=True # Store images as base64 data you can actually use
        ),
        "docx": lambda: partition_docx(
            filename=temp_file_path,
            strategy="hi_res",
            infer_table_structure=True
        ),
        "pptx": lambda: partition_pptx(
            filename=temp_file_path,
            strategy="hi_res",
            infer_table_structure=True
        ),
        "txt": lambda: partition_text(
            filename=temp_file_path,
        ),
        "md": lambda: partition_md(
            filename=temp_file_path,
        )
    }
    
    if file_type not in supported_file_types:
        raise ValueError(f"Unsupported file type: {file_type}. Accepted file types: {list(supported_file_types.keys())}")
    
    # trailing () executes that lambda function
    return supported_file_types[file_type]()


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

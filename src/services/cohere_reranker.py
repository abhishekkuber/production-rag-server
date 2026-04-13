import cohere
from src.config.index import app_config

cohere_reranker = cohere.ClientV2(app_config['cohere_api_key'])

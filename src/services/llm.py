from src.config.index import app_config
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings, ChatHuggingFace
from langchain_huggingface.llms import HuggingFaceEndpoint

open_ai_models = {
    "embedding_model": OpenAIEmbeddings(
        model="text-embedding-3-large",
        api_key=app_config['openai_api_key'],
        dimensions=1536 # !DO NOT CHANGE THIS VALUE!
    ),
    "summary_llm": ChatOpenAI(
        model="gpt-4o-mini",
        api_key=app_config['openai_api_key'],
        temperature=0,
    ), 
    "chat_llm": ChatOpenAI(
        model="gpt-4o-mini",
        api_key=app_config['openai_api_key'],
        temperature=0,
    )
}


'''
embedding_model : the model to be used when embedding chunks
summary_llm : the model to be used when you are summarizing the chunks which are multimodal. MAKE SURE THAT THE LLM YOU USE IS MULTIMODAL
chat_llm : the model to be used when you are chatting normally with the llm. MAKE SURE THAT THE LLM YOU USE IS MULTIMODAL
'''
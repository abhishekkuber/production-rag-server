from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routes.files import router as file_routes
from src.routes.users import router as user_routes
from src.routes.chats import router as chat_routes
from src.routes.projects import router as project_routes

from src.config.index import app_config


# Create FastAPI app
app = FastAPI(
    title="Production Ready RAG API",
    description="Backend API for Production Ready RAG API",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_routes, prefix="/api/users")
app.include_router(project_routes, prefix="/api/projects")
app.include_router(file_routes, prefix="/api/projects")
app.include_router(chat_routes, prefix="/api/chats")

# Health check endpoints
@app.get("/")
def root():
    return {"message": "Production Ready RAG API is up and running!"}

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0"
    }

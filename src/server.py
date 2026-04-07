from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routes.files import router as file_routes
from src.routes.users import router as user_routes
from src.routes.chats import router as chat_routes
from src.routes.projects import router as project_routes
from src.config.logging import configure_logging, get_logger
from src.middleware.logging_middleware import LoggingMiddleware

# Configure logging before anything else
configure_logging()
logger = get_logger(__name__)

logger.info("initializing_application", version="1.0.0")


# Create FastAPI app
app = FastAPI(
    title="Production Ready RAG API",
    description="Backend API for Production Ready RAG API",
    version="1.0.0",
    redirect_slashes=False
)

# Add logging middleware (should be first to capture all requests)
app.add_middleware(LoggingMiddleware)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("middleware_configured")

app.include_router(user_routes, prefix="/api/users")
app.include_router(project_routes, prefix="/api/projects")
app.include_router(file_routes, prefix="/api/projects")
app.include_router(chat_routes, prefix="/api/chats")

logger.info("routes_registered", route_count=4)

# Health check endpoints
@app.get("/")
def root():
    return {
        "name": "Production RAG API",
        "status": "running",
        "version": "1.0.0"
    }

@app.get("/health")
def health_check():
    """Health check endpoint."""
    logger.debug("health_check_called")
    return {
        "status": "healthy",
        "version": "1.0.0"
    }

logger.info("application_ready")
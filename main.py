from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from routes import users, projects
from dotenv import load_dotenv
import os

load_dotenv()


# Create FastAPI app
app = FastAPI(
    title="Production Ready RAG API",
    description="Backend API for Production Ready RAG API",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(projects.router)

# Health check endpoints
@app.get("/")
async def root():
    return {"message": "Production Ready RAG API is up and running!"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0"
    }

 
# @app.get("/posts")
# async def get_all_posts():
#     try: 
#         result = supabase.table("posts").select("*").order("created_at", desc=True).execute()
#         return result.data
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from dotenv import load_dotenv
from pathlib import Path

from .models.database import init_db
from .api.routes import router

load_dotenv()

app = FastAPI(
    title="Smart Swap AI System",
    description="Hybrid AI system for intelligent product swapping with rule-based and LLM-driven orchestration",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(router)

@app.get("/")
async def serve_home():
    return FileResponse(str(static_dir / "index.html"))

@app.get("/demo")
async def serve_demo():
    return FileResponse(str(static_dir / "demo.html"))

@app.on_event("startup")
async def startup_event():
    init_db()
    print("Database initialized successfully!")
    print("Smart Swap AI System is running...")
    print("Visit http://localhost:5000/docs for API documentation")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

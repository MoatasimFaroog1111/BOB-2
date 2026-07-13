from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import documents, journal

app = FastAPI(
    title="GuardianAI Accountant",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    documents.router,
    prefix="/documents",
    tags=["Documents"],
)

app.include_router(
    journal.router,
    prefix="/journal",
    tags=["Journal Entries"],
)


@app.get("/")
def root():
    return {
        "message": "GuardianAI Accountant Backend is running"
    }

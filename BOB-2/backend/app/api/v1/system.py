from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()


@router.get("/status")
def system_status():
    return {
        "app": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "status": "running",
        "api_version": "v1",
        "guardrails": "enabled",
        "human_approval": "required_for_financial_posting",
    }

from importlib.metadata import version

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", version=version("airsight"))

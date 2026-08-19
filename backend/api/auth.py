"""Auth-related endpoints: exposes who the backend thinks the caller is."""
from fastapi import APIRouter, Depends

from backend.auth.entra import get_current_user
from backend.models.auth import UserContext

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
async def me(user: UserContext = Depends(get_current_user)) -> dict:
    return {"oid": user.oid, "upn": user.upn, "name": user.name}

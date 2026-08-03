"""API аналитики — только для админов."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import require_admin
from app.admin.service import full_report
from app.db import get_session
from app.models import User

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/analytics")
async def analytics(_: User = Depends(require_admin),
                    session: AsyncSession = Depends(get_session)):
    return await full_report(session)

"""Provision deterministic local identity rows; never active in OIDC mode."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from course_tutor_api.db import Tenant, User
from course_tutor_contracts.enums import UserRole
from course_tutor_shared import AuthMode, Settings


async def ensure_local_identity(engine: AsyncEngine, settings: Settings) -> None:
    if settings.auth_mode is not AuthMode.LOCAL:
        return
    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await session.get(Tenant, settings.local_tenant_id)
        if tenant is None:
            session.add(
                Tenant(
                    id=settings.local_tenant_id,
                    slug=settings.local_tenant_slug,
                    name=settings.local_tenant_name,
                )
            )
            await session.flush()
        user = await session.get(User, settings.local_user_id)
        if user is None:
            session.add(
                User(
                    id=settings.local_user_id,
                    tenant_id=settings.local_tenant_id,
                    external_subject=f"local:{settings.local_user_id}",
                    display_name=settings.local_user_display_name,
                    role=UserRole(settings.local_user_role),
                )
            )
        elif user.tenant_id != settings.local_tenant_id:
            raise RuntimeError("LOCAL_USER_ID belongs to a different tenant")
        await session.commit()


__all__ = ["ensure_local_identity"]

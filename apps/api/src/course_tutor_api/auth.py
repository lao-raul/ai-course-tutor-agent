"""Compatibility exports for the shared authentication package.

New applications import :mod:`course_tutor_auth` directly. Keeping these exports
avoids breaking existing Agent API imports.
"""

from course_tutor_auth import (
    AuthProvider,
    LocalAuthProvider,
    OIDCAuthProvider,
    Principal,
    create_auth_provider,
    get_current_principal,
    principal_can_access_course,
    require_course_admin,
)

__all__ = [
    "AuthProvider",
    "LocalAuthProvider",
    "OIDCAuthProvider",
    "Principal",
    "create_auth_provider",
    "get_current_principal",
    "principal_can_access_course",
    "require_course_admin",
]

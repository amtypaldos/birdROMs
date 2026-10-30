from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.accounts.services import MEMBER, SUPER_ADMIN, user_role


class IsSuperAdminOrReadOnlyRole(BasePermission):
    """
    Reads (list, search, download, covers): readonly, member, super_admin.
    Upload (the `create` action): member and super_admin.
    Every other write (edit, delete, scrape): super_admin only.
    A Django superuser counts as super_admin; a user with no role can do nothing.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        role = user_role(request.user)
        if role is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if getattr(view, "action", None) == "create":
            return role in (SUPER_ADMIN, MEMBER)
        return role == SUPER_ADMIN


class IsPlaylistOwnerOrReadOnly(BasePermission):
    """Any authenticated user may read a playlist; only the user who created it may change it."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or obj.created_by_id == request.user.id


class IsSuperAdmin(BasePermission):
    """Library administration: super admins only."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and user_role(request.user) == SUPER_ADMIN)

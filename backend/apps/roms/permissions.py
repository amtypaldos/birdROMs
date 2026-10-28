from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.accounts.services import SUPER_ADMIN, user_role


class IsSuperAdminOrReadOnlyRole(BasePermission):
    """
    super_admin group can write.
    readonly group can only read.
    Exception: any authenticated user may upload (create) a ROM.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Deliberate loosening for a trusted friend group: uploads are open to every signed-in
        # user. RBAC is deferred; re-tighten here (drop this branch) when roles are enforced.
        if getattr(view, "action", None) == "create":
            return True
        if request.method in SAFE_METHODS:
            return request.user.groups.filter(name__in=["readonly", "super_admin"]).exists() or request.user.is_superuser
        return request.user.is_superuser or request.user.groups.filter(name="super_admin").exists()


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

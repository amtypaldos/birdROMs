from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsSuperAdminOrReadOnlyRole(BasePermission):
    """
    super_admin group can write.
    readonly group can only read.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return request.user.groups.filter(name__in=["readonly", "super_admin"]).exists() or request.user.is_superuser
        return request.user.is_superuser or request.user.groups.filter(name="super_admin").exists()


class IsPlaylistOwnerOrReadOnly(BasePermission):
    """Any authenticated user may read a playlist; only the user who created it may change it."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or obj.created_by_id == request.user.id

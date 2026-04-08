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

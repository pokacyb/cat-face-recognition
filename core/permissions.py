from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied


class IsMember(permissions.BasePermission):

    def has_permissions(self, request, view):
        if request.user.is_authentificated:
            if request.user.is_member or request.user.on_free_trial:
                return True
            else:
                raise PermissionDenied(
                    "You must be a member to make this request")
        else:
            raise PermissionDenied(
                "You must be logged in to make this request")

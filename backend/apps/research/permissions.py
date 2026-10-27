from rest_framework.permissions import BasePermission


class IsProjectOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, 'owner', None)
        if owner is None:
            owner = getattr(getattr(obj, 'project', None), 'owner', None)
        if owner is None:
            owner = getattr(getattr(getattr(obj, 'document', None), 'project', None), 'owner', None)
        return owner == request.user

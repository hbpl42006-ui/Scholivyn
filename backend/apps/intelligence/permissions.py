from rest_framework.permissions import BasePermission


class IsAnalysisOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        return getattr(obj, 'owner_id', None) == request.user.pk or getattr(getattr(obj, 'job', None), 'owner_id', None) == request.user.pk

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class ScholivynUserAdmin(UserAdmin):
    """Admin configuration that preserves Django's secure password flows."""

    list_display = (
        "username",
        "email",
        "full_name",
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
        "date_joined",
    )
    search_fields = ("username", "email", "full_name")
    list_filter = ("is_active", "role", "is_staff", "is_superuser")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal info",
            {"fields": ("full_name", "first_name", "last_name", "email")},
        ),
        (
            "Account",
            {"fields": ("role", "is_active", "date_joined", "last_login")},
        ),
        (
            "Permissions",
            {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")},
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "full_name",
                    "role",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        # Account activation is exclusively controlled by the email-verification
        # flow, including for superusers using the admin.
        readonly = set(super().get_readonly_fields(request, obj))
        readonly.update(("is_active", "date_joined", "last_login"))

        # Staff with user-change permission can manage profile details, but
        # only superusers may grant roles or Django permissions.
        if not request.user.is_superuser:
            readonly.update(
                ("role", "is_staff", "is_superuser", "groups", "user_permissions")
            )
        return tuple(readonly)

    def save_model(self, request, obj, form, change):
        # Admin-created accounts must complete the normal verification flow.
        if not change:
            obj.is_active = False
        super().save_model(request, obj, form, change)


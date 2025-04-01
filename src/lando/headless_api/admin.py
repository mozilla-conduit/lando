from django import forms
from django.contrib import admin

from lando.headless_api.models.tokens import ApiToken


class ApiTokenForm(forms.ModelForm):
    """Form to create tokens via the admin UI."""

    # This field is not stored in the database—it’s just for display after creation.
    raw_token = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"readonly": "readonly"}),
        help_text="This token is shown only once when created.",
    )

    class Meta:
        model = ApiToken

        # Only require the user (or any non-sensitive fields)
        fields = ["user"]

    def save(self, commit=True):
        # When creating a new token via the admin form, use create_token.
        if not self.instance.pk:
            # Call create_token which creates the APIToken instance and returns the raw token.
            raw_token = ApiToken.create_token(self.cleaned_data["user"])
            # Attach the raw token to the instance temporarily (not saved to DB)
            self.instance.raw_token = raw_token
            return self.instance
        else:
            return super().save(commit)


class ApiTokenAdmin(admin.ModelAdmin):

    form = ApiTokenForm

    list_display = ("user", "token_prefix", "created_at")

    # Mark these fields as read-only in the admin.
    readonly_fields = ("token_prefix", "token_hash", "created_at")

    def response_add(self, request, obj, post_url_continue=None):
        # After the token is created, check if the raw token is attached and display it.
        if hasattr(obj, "raw_token"):
            self.message_user(
                request, f"New token for {obj.user.username}: {obj.raw_token}"
            )
        return super().response_add(request, obj, post_url_continue)


admin.site.register(ApiToken, ApiTokenAdmin)

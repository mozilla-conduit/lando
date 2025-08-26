from django import forms

from lando.api.legacy.uplift import get_uplift_repositories
from lando.main.models import Repo


class TransplantRequestForm(forms.Form):
    landing_path = forms.JSONField(widget=forms.widgets.HiddenInput)
    confirmation_token = forms.CharField(
        widget=forms.widgets.HiddenInput, required=False
    )
    flags = forms.JSONField(widget=forms.widgets.HiddenInput, required=False)


class UpliftRequestForm(forms.Form):
    """Form used to request uplift of a stack."""

    revision_id = forms.RegexField(
        regex="^D[0-9]+$",
        widget=forms.widgets.HiddenInput,
        required=False,
    )
    repository = forms.ChoiceField(
        widget=forms.Select(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        uplift_repos = get_uplift_repositories()
        self.fields["repository"].choices = [(repo, repo) for repo in uplift_repos]

    def clean_repository(self) -> str:
        repo_short_name = self.cleaned_data["repository"]
        try:
            repository = Repo.objects.get(short_name=repo_short_name)
        except Repo.DoesNotExist:
            raise forms.ValidationError(
                f"Repository {repo_short_name} is not a repository known to Lando. "
                "Please select an uplift repository to create the uplift request."
            )

        if not repository.approval_required:
            raise forms.ValidationError(
                f"Repository {repo_short_name} is not an uplift repository. "
                "Please select an uplift repository to create the uplift request."
            )
        return repository


class UserSettingsForm(forms.Form):
    """Form used to provide the Phabricator API Token."""

    phabricator_api_key = forms.RegexField(
        required=False,
        regex="^api-[a-z0-9]{28}$",
        label="Phabricator API Key",
    )
    phabricator_api_key.widget.attrs.update({"class": "input"})
    reset_key = forms.BooleanField(required=False, label="Delete")

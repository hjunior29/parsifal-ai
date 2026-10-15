from django import forms

from parsifal.apps.reviews.models import Review


class ReviewSettingsForm(forms.ModelForm):
    name = forms.SlugField(
        widget=forms.TextInput(attrs={"class": "form-control"}),
        label="URL",
        help_text="Only letters, numbers, underscores or hyphens are allowed.",
        max_length=255,
    )

    review_type = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Review type",
        choices=Review.REVIEW_TYPES,
        help_text=(
            "Systematic literature review (Kitchenham & Charters) or systematic mapping study (Petersen et al.)."
        ),
    )

    class Meta:
        model = Review
        fields = [
            "name",
            "review_type",
        ]

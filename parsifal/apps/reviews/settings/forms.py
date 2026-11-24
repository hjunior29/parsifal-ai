from django import forms

from parsifal.apps.core.exceptions import DomainError
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.services import reviews


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
            "Systematic literature review (Kitchenham & Charters), systematic mapping study (Petersen et al.) or "
            "rapid review (Cartaxo, Pinto & Soares)."
        ),
    )

    class Meta:
        model = Review
        fields = [
            "name",
            "review_type",
        ]

    def clean_review_type(self):
        review_type = self.cleaned_data["review_type"]
        try:
            reviews.check_type_change(Review.objects.get(pk=self.instance.pk), review_type)
        except DomainError as error:
            raise forms.ValidationError(str(error))
        return review_type

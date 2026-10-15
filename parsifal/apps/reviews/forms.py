from django import forms

from parsifal.apps.reviews.models import Review


class CreateReviewForm(forms.ModelForm):
    title = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Systematic literature review's title"}),
        max_length=255,
    )
    description = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "placeholder": "Give a brief description of your systematic literature review",
            }
        ),
        max_length=500,
        help_text="Try to keep it short, max 500 characters :)",
        required=False,
    )
    review_type = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-control"}),
        choices=Review.REVIEW_TYPES,
        initial=Review.SLR,
        label="Review type",
        required=False,
    )

    class Meta:
        model = Review
        fields = [
            "title",
            "description",
            "review_type",
        ]

    def clean_review_type(self):
        return self.cleaned_data.get("review_type") or Review.SLR


class ReviewForm(forms.ModelForm):
    title = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}), max_length=255)
    description = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control expanding", "rows": "4"}), max_length=500, required=False
    )

    class Meta:
        model = Review
        fields = [
            "title",
            "description",
        ]

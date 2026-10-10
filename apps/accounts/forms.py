from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Organization, User


class SignupForm(forms.Form):
    organization_name = forms.CharField(max_length=200, label="Business name")
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password


class ProfileForm(forms.ModelForm):
    """The details a person may change about themselves. Email and role are not here."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]


class BusinessForm(forms.ModelForm):
    """A landlord's business name, as tenants see it."""

    class Meta:
        model = Organization
        fields = ["name"]
        labels = {"name": "Business name"}

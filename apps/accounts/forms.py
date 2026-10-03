from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import User


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

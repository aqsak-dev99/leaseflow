from django import forms
from django.contrib.auth.password_validation import validate_password


class DateInput(forms.DateInput):
    input_type = "date"


class InviteForm(forms.Form):
    email = forms.EmailField(label="Tenant's email")
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    start_date = forms.DateField(label="Lease starts", widget=DateInput)
    end_date = forms.DateField(label="Lease ends", widget=DateInput)
    rent_amount = forms.DecimalField(
        label="Monthly rent (Rs.)", min_value=1, max_digits=10, decimal_places=2
    )
    deposit = forms.DecimalField(
        label="Security deposit (Rs.)", min_value=0, max_digits=10, decimal_places=2, initial=0
    )
    due_day = forms.IntegerField(label="Rent due on day", min_value=1, max_value=28, initial=5)


class NewAccountForm(forms.Form):
    """For an invited tenant who has no account yet."""

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password_again = forms.CharField(
        label="Repeat password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("password_again") != data["password"]:
            self.add_error("password_again", "The two passwords do not match.")
        return data


class ExistingAccountForm(forms.Form):
    """For an invited tenant who already has an account: they prove it with their password."""

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )

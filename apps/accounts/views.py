from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import SignupForm
from .services import signup_landlord


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = signup_landlord(**form.cleaned_data)
        login(request, user)
        return redirect("dashboard:home")
    return render(request, "accounts/signup.html", {"form": form})

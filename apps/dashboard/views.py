from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone


def home(request):
    return render(request, "dashboard/home.html")


def htmx_check(request):
    now = timezone.localtime().strftime("%H:%M:%S")
    return HttpResponse(f"<p>HTMX works. Server time: {now}</p>")

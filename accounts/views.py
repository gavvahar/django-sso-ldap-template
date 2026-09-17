from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def home(request):
    """Public landing page with a login button."""
    return render(request, "accounts/home.html")


@login_required
def profile(request):
    """Requires SSO login; shows what came back from the provider."""
    return render(request, "accounts/profile.html")

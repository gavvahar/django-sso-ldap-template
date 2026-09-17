from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # /oidc/authenticate/ starts login, /oidc/callback/ receives the code,
    # /oidc/logout/ (POST) ends the session.
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("", include("accounts.urls")),
]

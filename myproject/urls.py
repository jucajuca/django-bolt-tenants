"""
URL configuration for myproject project.
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('django_bolt.urls')),
]

if 'debug_toolbar' in settings.INSTALLED_APPS:
    urlpatterns.append(path('__debug__/', include('debug_toolbar.urls')))

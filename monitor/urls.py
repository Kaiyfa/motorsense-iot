"""
Main Project URL Configuration with Authentication
URL configuration for monitor project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from dashboard import views as dashboard_views

urlpatterns = [
    # Admin site
    path('admin/', admin.site.urls),
    
    # Authentication URLs
    path('accounts/', include('django.contrib.auth.urls')),  
    path('login/', dashboard_views.login_view, name='login'),  
    path('logout/', dashboard_views.logout_view, name='logout'),  
    
    # Dashboard app (main routes)
    path('', include('dashboard.urls', namespace='dashboard')), 
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
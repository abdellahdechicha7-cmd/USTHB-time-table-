from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path('', include('timetable.urls_public')),
    path('dashboard/', include('timetable.urls_dashboard')),
    path('dashboard/', include('timetable.urls_notes')),
    path('login/', auth_views.LoginView.as_view(redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('django-admin/', admin.site.urls),
]

from django.urls import path

from . import views_dashboard as views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
]

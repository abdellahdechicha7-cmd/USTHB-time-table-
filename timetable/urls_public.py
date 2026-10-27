from django.urls import path

from . import views_public as views

app_name = 'public'

urlpatterns = [
    path('', views.home, name='home'),
    path('s/<slug:slug>/', views.space, name='space'),
    path('s/<slug:slug>/w/<str:week>/', views.space, name='week'),
]

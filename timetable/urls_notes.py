from django.urls import path

from . import views_notes as views

app_name = 'notes'

urlpatterns = [
    path('s/<slug:slug>/notes/', views.note_list, name='list'),
    path('s/<slug:slug>/notes/new/', views.note_create, name='create'),
    path('s/<slug:slug>/notes/<int:pk>/', views.note_edit, name='edit'),
    path('s/<slug:slug>/notes/<int:pk>/delete/', views.note_delete, name='delete'),
]

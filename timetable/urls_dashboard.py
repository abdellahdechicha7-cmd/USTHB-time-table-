from django.urls import path

from . import views_dashboard as views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),

    # Spaces (superuser)
    path('spaces/new/', views.space_create, name='space_create'),
    path('spaces/<slug:slug>/edit/', views.space_edit, name='space_edit'),
    path('spaces/<slug:slug>/delete/', views.space_delete, name='space_delete'),

    # Admin accounts (superuser)
    path('admins/', views.admins, name='admins'),
    path('admins/new/', views.admin_create, name='admin_create'),
    path('admins/<int:pk>/', views.admin_edit, name='admin_edit'),
    path('admins/<int:pk>/password/', views.admin_password, name='admin_password'),
    path('admins/<int:pk>/toggle-active/', views.admin_toggle_active, name='admin_toggle_active'),

    # Space (space admins)
    path('s/<slug:slug>/', views.space_current, name='space'),
    path('s/<slug:slug>/w/<str:week>/', views.week_editor, name='week'),
    path('s/<slug:slug>/w/<str:week>/publish/', views.week_publish, name='week_publish'),
    path('s/<slug:slug>/w/<str:week>/copy/', views.week_copy, name='week_copy'),
    path('s/<slug:slug>/w/<str:week>/start/', views.week_start_blank, name='week_start'),
    path('s/<slug:slug>/w/<str:week>/session/new/', views.session_create, name='session_create'),
    path('s/<slug:slug>/session/<int:pk>/edit/', views.session_edit, name='session_edit'),
    path('s/<slug:slug>/session/<int:pk>/delete/', views.session_delete, name='session_delete'),
    path('s/<slug:slug>/session/<int:pk>/toggle-cancel/', views.session_toggle_cancel, name='session_toggle_cancel'),
    path('s/<slug:slug>/settings/', views.space_settings, name='settings'),
    path('s/<slug:slug>/settings/<str:kind>/add/', views.settings_save, name='settings_add'),
    path('s/<slug:slug>/settings/<str:kind>/<int:pk>/', views.settings_save, name='settings_edit'),
    path('s/<slug:slug>/settings/<str:kind>/<int:pk>/delete/', views.settings_delete, name='settings_delete'),
    path('s/<slug:slug>/activity/', views.activity, name='activity'),
]

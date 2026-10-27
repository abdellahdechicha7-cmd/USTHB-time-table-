from django.contrib import admin

from . import models


class MembershipInline(admin.TabularInline):
    model = models.SpaceMembership
    extra = 0


@admin.register(models.Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'major', 'section', 'is_active']
    prepopulated_fields = {'slug': ['name']}
    inlines = [MembershipInline]


@admin.register(models.Week)
class WeekAdmin(admin.ModelAdmin):
    list_display = ['space', 'start', 'status']
    list_filter = ['space', 'status']


@admin.register(models.Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ['subject', 'kind', 'day', 'timeslot', 'week', 'is_cancelled']
    list_filter = ['week__space', 'kind', 'is_cancelled']


@admin.register(models.AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'user', 'space', 'action', 'detail']
    list_filter = ['space', 'action']


admin.site.register([models.Group, models.TimeSlot, models.Subject, models.Note])

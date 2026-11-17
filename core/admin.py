from django.contrib import admin
from .models import UserProfile, Project, DailyReport, ReportComment

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'department', 'status_message', 'is_online')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'role')

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'created_by', 'created_at', 'member_count')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('members',)

@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = ('author', 'project', 'date', 'created_at', 'has_blockers')
    list_filter = ('project', 'date', 'author')
    search_fields = ('author__username', 'yesterday_work', 'today_plan', 'blockers')
    filter_horizontal = ('tagged_users',)

@admin.register(ReportComment)
class ReportCommentAdmin(admin.ModelAdmin):
    list_display = ('author', 'report', 'created_at')
    search_fields = ('author__username', 'message')

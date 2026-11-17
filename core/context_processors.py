from .models import Project, DailyReport, Huddle
from django.contrib.auth.models import User
from django.core.cache import cache

def workspace_context(request):
    if not request.user.is_authenticated:
        return {
            'current_user': None,
            'sidebar_projects': [],
            'all_workspace_users': [],
            'my_mentions_count': 0,
            'active_huddle_slugs': [],
            'active_huddle_user_ids': [],
        }

    # Fetch cached workspace lists (refreshed every 5s or upon updates)
    projects = cache.get('workspace_sidebar_projects')
    if projects is None:
        projects = list(Project.objects.all().prefetch_related('members'))
        cache.set('workspace_sidebar_projects', projects, timeout=5)

    all_users = cache.get('workspace_all_users')
    if all_users is None:
        all_users = list(User.objects.all().select_related('profile').order_by('first_name', 'username'))
        cache.set('workspace_all_users', all_users, timeout=5)

    return {
        'current_user': request.user,
        'sidebar_projects': projects,
        'all_workspace_users': all_users,
        'my_mentions_count': 0,
        'active_huddle_slugs': [],
        'active_huddle_user_ids': [],
    }



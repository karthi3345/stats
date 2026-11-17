from .models import Project, DailyReport, Huddle
from django.contrib.auth.models import User

def workspace_context(request):
    projects = Project.objects.all().prefetch_related('members')
    all_users = User.objects.all().select_related('profile').order_by('first_name', 'username')
    
    # Calculate how many reports tag the current user
    mentions_count = 0
    if request.user.is_authenticated:
        mentions_count = DailyReport.objects.filter(tagged_users=request.user).count()
        
    active_huddle_slugs = list(Huddle.objects.filter(is_active=True).values_list('project__slug', flat=True))
    active_huddle_user_ids = list(Huddle.objects.filter(is_active=True).values_list('participants__user_id', flat=True).filter(participants__is_left=False))

    return {
        'current_user': request.user if request.user.is_authenticated else None,
        'sidebar_projects': projects,
        'all_workspace_users': all_users,
        'my_mentions_count': mentions_count,
        'active_huddle_slugs': active_huddle_slugs,
        'active_huddle_user_ids': active_huddle_user_ids,
    }

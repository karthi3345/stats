import re
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from io import BytesIO
from django.http import JsonResponse, HttpResponse
from django.db import models
from django.db.models import Count, Q
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Project, DailyReport, ReportComment, UserProfile, ReportReaction, ProjectTask, KanbanColumn, TaskComment, TaskSubtask, TaskAttachment, Huddle, HuddleParticipant, ProjectConfluenceSection, DirectMessage
from .forms import ProjectForm, DailyReportForm


def auto_tag_mentions(report, text_corpus):
    """Parses @usernames in text and adds matching users to report.tagged_users"""
    usernames = re.findall(r'@([a-zA-Z0-9_\.\-]+)', text_corpus)
    for uname in usernames:
        try:
            user = User.objects.get(username__iexact=uname)
            if user != report.author:
                report.tagged_users.add(user)
        except User.DoesNotExist:
            pass


# ==============================================================================
# AUTHENTICATION VIEWS
# ==============================================================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    demo_users = User.objects.all().select_related('profile')[:6]

    if request.method == 'POST':
        # Check if quick demo login was clicked
        demo_user_id = request.POST.get('demo_user_id')
        if demo_user_id:
            user = get_object_or_404(User, id=demo_user_id)
            login(request, user)
            messages.success(request, f"Welcome back to StatusPulse, {user.get_full_name() or user.username}!")
            return redirect('dashboard')

        # Standard username/email login (supports case-insensitive and email)
        identifier = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        user = authenticate(request, username=identifier, password=password)
        if user is None:
            # Try case-insensitive username match or email match
            matched_user = User.objects.filter(
                models.Q(username__iexact=identifier) | models.Q(email__iexact=identifier)
            ).first()
            if matched_user:
                user = authenticate(request, username=matched_user.username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
            next_url = request.GET.get('next', 'dashboard')
            return redirect(next_url)
        else:
            messages.error(request, "Invalid username or password. Please try again.")


    return render(request, 'login.html', {'demo_users': demo_users})


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        role = request.POST.get('role', 'Software Engineer').strip()
        password = request.POST.get('password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return render(request, 'register.html')

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
            return render(request, 'register.html')

        if confirm_password and password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, f"Username @{username} is already taken.")
            return render(request, 'register.html')

        if email and User.objects.filter(email__iexact=email).exists():
            messages.error(request, f"Email {email} is already registered.")
            return render(request, 'register.html')

        # Parse first and last name
        parts = full_name.split(' ', 1)
        first_name = parts[0] if parts else username
        last_name = parts[1] if len(parts) > 1 else ''

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        # Update profile
        if hasattr(user, 'profile'):
            user.profile.role = role
            user.profile.save()

        # Add new user to all existing projects automatically
        for p in Project.objects.all():
            p.members.add(user)

        login(request, user)
        messages.success(request, f"Account created! Welcome to StatusPulse, {user.get_full_name() or user.username}!")
        return redirect('dashboard')

    return render(request, 'register.html')


def logout_view(request):
    logout(request)
    messages.info(request, "You have been signed out of StatusPulse.")
    return redirect('login')


# ==============================================================================
# MAIN APPLICATION VIEWS
# ==============================================================================

@login_required(login_url='login')
def dashboard(request):
    first_project = Project.objects.first()
    if first_project:
        return redirect('project_detail', slug=first_project.slug)
    return redirect('all_reports')


@login_required(login_url='login')
def project_detail(request, slug):
    current_user = request.user
    project = get_object_or_404(Project.objects.prefetch_related('members', 'members__profile'), slug=slug)

    # Date and user filters
    date_filter = request.GET.get('date')
    member_filter = request.GET.get('member')

    reports_qs = DailyReport.objects.filter(project=project)\
        .select_related('author', 'author__profile', 'project')\
        .prefetch_related('tagged_users', 'tagged_users__profile', 'comments', 'comments__author')\
        .order_by('date', 'created_at')

    if date_filter:
        try:
            parsed_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            reports_qs = reports_qs.filter(date=parsed_date)
        except ValueError:
            pass

    if member_filter:
        reports_qs = reports_qs.filter(author__username=member_filter)

    # Group reports by date
    reports_by_date = {}
    for r in reports_qs:
        date_key = r.date
        if date_key not in reports_by_date:
            reports_by_date[date_key] = []
        reports_by_date[date_key].append(r)

    # Non-members available to add
    project_member_ids = project.members.values_list('id', flat=True)
    available_users = User.objects.exclude(id__in=project_member_ids).select_related('profile')

    # Group reports for Confluence view inside project
    days_data = []
    confluence_by_date = {}

    # 1. Fetch any manually added date sections
    manual_sections = ProjectConfluenceSection.objects.filter(project=project)
    for ms in manual_sections:
        if ms.date not in confluence_by_date:
            confluence_by_date[ms.date] = []

    # 2. Fetch existing structured Confluence reports (exclude quick chat messages)
    confluence_qs = DailyReport.objects.filter(project=project)\
        .exclude(what_done_today='', yesterday_work='', today_plan='')\
        .select_related('author', 'author__profile').order_by('-date', '-id')

    confluence_reports_count = confluence_qs.count()

    for r in confluence_qs:
        date_key = r.date
        if date_key not in confluence_by_date:
            confluence_by_date[date_key] = []
        confluence_by_date[date_key].append(r)

    # If no reports or sections exist, provide today's date
    if not confluence_by_date:
        today = timezone.now().date()
        confluence_by_date[today] = []

    for date_key, rlist in sorted(confluence_by_date.items(), reverse=True):
        custom_sec = manual_sections.filter(date=date_key).first()
        day_title = custom_sec.display_title if custom_sec else f"{date_key.strftime('%A')} <{date_key.strftime('%d-%m-%Y')}>"
        day_anchor = f"day-{date_key.strftime('%Y%m%d')}"
        days_data.append({
            'date': date_key,
            'title': day_title,
            'anchor': day_anchor,
            'reports': rlist,
            'is_manual': bool(custom_sec),
            'section_id': custom_sec.id if custom_sec else None,
        })

    # Initial form
    form = DailyReportForm(initial={'date': timezone.now().date()})
    form.fields['tagged_users'].queryset = project.members.all()

    # Management / Dynamic Kanban Columns & Tasks
    columns_qs = list(project.kanban_columns.all().order_by('order', 'id'))
    if not columns_qs:
        # Default columns fallback
        for name, slug, order, color in [('To Do', 'todo', 0, '#FFAB00'), ('In Progress', 'inprogress', 1, '#0052CC'), ('Done', 'done', 2, '#00875A')]:
            col, _ = KanbanColumn.objects.get_or_create(project=project, slug=slug, defaults={'name': name, 'order': order, 'color': color})
            columns_qs.append(col)

    all_tasks = list(project.tasks.select_related('assignee', 'assignee__profile', 'created_by').order_by('id'))
    total_tasks_count = len(all_tasks)

    # Attach tasks to each column
    columns_data = []
    for col in columns_qs:
        col_tasks = [t for t in all_tasks if t.status == col.slug]
        columns_data.append({
            'column': col,
            'tasks': col_tasks,
            'count': len(col_tasks),
        })

    tasks_todo = [t for t in all_tasks if t.status == 'todo']
    tasks_inprogress = [t for t in all_tasks if t.status == 'inprogress']
    tasks_done = [t for t in all_tasks if t.status == 'done']

    # Project Channel Analytics Calculations
    completed_tasks_count = len(tasks_done)
    inprogress_tasks_count = len(tasks_inprogress)
    open_tasks_count = total_tasks_count - completed_tasks_count
    completion_percentage = round((completed_tasks_count / total_tasks_count * 100), 1) if total_tasks_count > 0 else 0

    # Issue type breakdown
    type_counts = {'story': 0, 'bug': 0, 'task': 0, 'epic': 0}
    priority_counts = {'critical': 0, 'urgent': 0, 'high': 0, 'medium': 0, 'low': 0}
    for t in all_tasks:
        if t.issue_type in type_counts:
            type_counts[t.issue_type] += 1
        p = t.priority.lower()
        if p in priority_counts:
            priority_counts[p] += 1

    # Team member workload for this project
    member_workload = []
    for member in project.members.all().select_related('profile'):
        assigned = [t for t in all_tasks if t.assignee_id == member.id]
        completed = [t for t in assigned if t.status == 'done']
        member_workload.append({
            'member': member,
            'assigned_count': len(assigned),
            'completed_count': len(completed),
            'open_count': len(assigned) - len(completed),
        })

    context = {
        'project': project,
        'reports_by_date': reports_by_date,
        'days_data': days_data,
        'report_count': reports_qs.count(),
        'confluence_reports_count': confluence_reports_count,
        'available_users': available_users,
        'form': form,
        'current_user': current_user,
        'active_filter_date': date_filter,
        'active_filter_member': member_filter,
        'project_members': project.members.all().select_related('profile'),
        'kanban_columns_data': columns_data,
        'kanban_columns': columns_qs,
        'tasks_todo': tasks_todo,
        'tasks_inprogress': tasks_inprogress,
        'tasks_done': tasks_done,
        'total_tasks_count': total_tasks_count,
        'completed_tasks_count': completed_tasks_count,
        'inprogress_tasks_count': inprogress_tasks_count,
        'open_tasks_count': open_tasks_count,
        'completion_percentage': completion_percentage,
        'type_counts': type_counts,
        'priority_counts': priority_counts,
        'member_workload': member_workload,
    }
    return render(request, 'project_detail.html', context)


@login_required(login_url='login')
def all_reports(request):
    current_user = request.user
    reports_qs = DailyReport.objects\
        .select_related('author', 'author__profile', 'project')\
        .prefetch_related('tagged_users', 'tagged_users__profile', 'comments', 'comments__author')\
        .order_by('date', 'created_at')

    date_filter = request.GET.get('date')
    member_filter = request.GET.get('member')
    project_filter = request.GET.get('project')
    tagged_me = request.GET.get('tagged_me')

    if tagged_me:
        reports_qs = reports_qs.filter(tagged_users=current_user)

    if project_filter:
        reports_qs = reports_qs.filter(project__slug=project_filter)

    if member_filter:
        reports_qs = reports_qs.filter(author__username=member_filter)

    if date_filter:
        try:
            parsed_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            reports_qs = reports_qs.filter(date=parsed_date)
        except ValueError:
            pass

    # Group reports by date
    reports_by_date = {}
    for r in reports_qs:
        date_key = r.date
        if date_key not in reports_by_date:
            reports_by_date[date_key] = []
        reports_by_date[date_key].append(r)

    context = {
        'reports_by_date': reports_by_date,
        'report_count': reports_qs.count(),
        'current_user': current_user,
        'active_filter_date': date_filter,
        'active_filter_member': member_filter,
        'active_filter_project': project_filter,
        'tagged_me': tagged_me,
    }
    return render(request, 'all_reports.html', context)


@login_required(login_url='login')
def project_confluence_view(request, slug):
    current_user = request.user
    project = get_object_or_404(Project.objects.prefetch_related('members', 'members__profile'), slug=slug)

    reports_qs = DailyReport.objects.filter(project=project)\
        .exclude(what_done_today='', yesterday_work='', today_plan='')\
        .select_related('author', 'author__profile').order_by('-date', '-id')

    # Group reports by date
    days_data = []
    reports_by_date = {}
    for r in reports_qs:
        date_key = r.date
        if date_key not in reports_by_date:
            reports_by_date[date_key] = []
        reports_by_date[date_key].append(r)

    if not reports_by_date:
        today = timezone.now().date()
        reports_by_date[today] = []

    for date_key, rlist in sorted(reports_by_date.items(), reverse=True):
        day_title = f"{date_key.strftime('%A')} <{date_key.strftime('%d-%m-%Y')}>"
        day_anchor = f"day-{date_key.strftime('%Y%m%d')}"
        days_data.append({
            'date': date_key,
            'title': day_title,
            'anchor': day_anchor,
            'reports': rlist
        })

    context = {
        'project': project,
        'days_data': days_data,
        'current_user': current_user,
        'project_members': project.members.all().select_related('profile'),
    }
    return render(request, 'confluence_view.html', context)


@require_POST
@login_required(login_url='login')
def submit_report(request, slug):
    current_user = request.user
    project = get_object_or_404(Project, slug=slug)

    # 1. Check if Daily Progress Report / Confluence entry was submitted
    yesterday_work = request.POST.get('yesterday_work', '').strip()
    today_plan = request.POST.get('today_plan', '').strip()
    what_done_today = request.POST.get('what_done_today', '').strip()
    issues_faced = request.POST.get('issues_faced', '').strip()
    needed_from_others = request.POST.get('needed_from_others', '').strip()
    blockers = request.POST.get('blockers', '').strip() or issues_faced
    priority = request.POST.get('priority', 'Medium').strip()
    links_notes = request.POST.get('links_notes', '').strip()
    date_str = request.POST.get('date')
    tagged_ids = request.POST.getlist('tagged_users')

    report_date = timezone.now().date()
    if date_str:
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    if yesterday_work or today_plan or what_done_today:
        report = DailyReport.objects.create(
            project=project,
            author=current_user,
            date=report_date,
            priority=priority,
            links_notes=links_notes,
            yesterday_work=yesterday_work or what_done_today,
            today_plan=today_plan,
            what_done_today=what_done_today or yesterday_work,
            issues_faced=issues_faced,
            needed_from_others=needed_from_others,
            blockers=blockers
        )
        if tagged_ids:
            report.tagged_users.set(User.objects.filter(id__in=tagged_ids))
        combined_text = f"{yesterday_work} {today_plan} {what_done_today} {needed_from_others} {blockers} {links_notes}"
        auto_tag_mentions(report, combined_text)

        if not project.members.filter(id=current_user.id).exists():
            project.members.add(current_user)

        messages.success(request, f"Daily progress report posted in #{project.name}!")
        referer = request.META.get('HTTP_REFERER', '')
        if 'confluence' in referer:
            return redirect('project_confluence', slug=slug)
        return redirect('project_detail', slug=slug)

    # 2. Check if quick chat message was sent
    content = request.POST.get('content', '').strip()
    if content:
        report = DailyReport.objects.create(
            project=project,
            author=current_user,
            date=timezone.now().date(),
            content=content
        )
        auto_tag_mentions(report, content)

        if not project.members.filter(id=current_user.id).exists():
            project.members.add(current_user)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({
                'status': 'ok',
                'id': report.id,
                'author': report.author.get_full_name() or report.author.username,
                'author_username': report.author.username,
                'author_role': report.author.profile.role if hasattr(report.author, 'profile') else 'Member',
                'author_initials': report.author.profile.initials if hasattr(report.author, 'profile') else report.author.username[:2].upper(),
                'author_color': report.author.profile.avatar_color if hasattr(report.author, 'profile') else '#1264A3',
                'content': report.content,
                'html': report.message_html,
                'time': report.created_at.strftime('%I:%M %p').lstrip('0'),
            })

        messages.success(request, f"Message sent in #{project.name}!")
        return redirect('project_detail', slug=slug)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'error': 'Please enter a message.'}, status=400)

    messages.error(request, "Please enter your progress report or message.")
    return redirect('project_detail', slug=slug)


@require_POST
@login_required(login_url='login')
def create_project(request):
    current_user = request.user
    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    color = request.POST.get('color', '#1264A3')
    member_ids = request.POST.getlist('members')

    if not name:
        messages.error(request, "Project name cannot be empty.")
        return redirect('dashboard')

    clean_name = name.lower().replace(' ', '-').lstrip('#')

    project, created = Project.objects.get_or_create(
        name=clean_name,
        defaults={
            'description': description,
            'color': color,
            'created_by': current_user
        }
    )

    if not created:
        messages.info(request, f"Project #{project.name} already exists.")
    else:
        project.members.add(current_user)
        if member_ids:
            selected_users = User.objects.filter(id__in=member_ids)
            project.members.add(*selected_users)
        messages.success(request, f"Project #{project.name} created successfully!")

    return redirect('project_detail', slug=project.slug)


@require_POST
@login_required(login_url='login')
def add_project_members(request, slug):
    project = get_object_or_404(Project, slug=slug)
    user_ids = request.POST.getlist('user_ids')
    if user_ids:
        users = User.objects.filter(id__in=user_ids)
        project.members.add(*users)
        messages.success(request, f"Added {users.count()} team member(s) to #{project.name}!")
    else:
        messages.warning(request, "No members selected to add.")
    return redirect('project_detail', slug=slug)


@require_POST
@login_required(login_url='login')
def remove_project_member(request, slug, user_id):
    project = get_object_or_404(Project, slug=slug)
    # Check if requester is the channel creator/owner or superuser/staff
    is_owner = (project.created_by == request.user) or (project.created_by is None) or request.user.is_staff
    if not is_owner:
        messages.error(request, f"Only the channel owner (@{project.created_by.username if project.created_by else 'Admin'}) can remove members from #{project.name}.")
        return redirect('project_detail', slug=slug)

    user_to_remove = get_object_or_404(User, id=user_id)
    if user_to_remove == project.created_by and not request.user.is_staff:
        messages.error(request, "The channel owner cannot be removed from their own channel.")
        return redirect('project_detail', slug=slug)

    project.members.remove(user_to_remove)
    messages.info(request, f"Removed {user_to_remove.get_full_name() or user_to_remove.username} from #{project.name}.")
    return redirect('project_detail', slug=slug)


@require_POST
@login_required(login_url='login')
def add_comment(request, report_id):
    current_user = request.user
    report = get_object_or_404(DailyReport, id=report_id)
    message = request.POST.get('message', '').strip()

    if message:
        comment = ReportComment.objects.create(
            report=report,
            author=current_user,
            message=message
        )
        auto_tag_mentions(report, message)
        messages.success(request, "Reply posted.")

    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('project_detail', slug=report.project.slug)


def switch_user(request, user_id):
    """Developer/Demo convenience tool: switch active logged-in user with 1-click"""
    user = get_object_or_404(User, id=user_id)
    login(request, user)
    messages.info(request, f"Switched active user to {user.get_full_name() or user.username} (@{user.username})")
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('dashboard')


@require_POST
@login_required(login_url='login')
def toggle_reaction(request, report_id):
    report = get_object_or_404(DailyReport, id=report_id)
    emoji = request.POST.get('emoji', '👍').strip()

    reaction = ReportReaction.objects.filter(report=report, user=request.user, emoji=emoji).first()
    if reaction:
        reaction.delete()
        action = 'removed'
    else:
        ReportReaction.objects.create(report=report, user=request.user, emoji=emoji)
        action = 'added'

    summary = report.get_reaction_summary(request.user)
    return JsonResponse({
        'status': 'ok',
        'action': action,
        'reactions': summary
    })


# ==============================================================================
# MANAGEMENT / KANBAN TASK VIEWS
# ==============================================================================

@require_POST
@login_required(login_url='login')
def create_task(request, slug):
    current_user = request.user
    project = get_object_or_404(Project, slug=slug)

    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    status = request.POST.get('status', 'todo').strip()
    
    # Check if status matches an existing column or fallback
    valid_column = project.kanban_columns.filter(slug=status).first()
    if not valid_column and status not in ['todo', 'inprogress', 'done']:
        first_col = project.kanban_columns.first()
        status = first_col.slug if first_col else 'todo'

    priority = request.POST.get('priority', 'medium').strip().lower()
    if priority not in ['low', 'medium', 'high', 'urgent', 'critical']:
        priority = 'medium'
    issue_type = request.POST.get('issue_type', 'task').strip().lower()
    if issue_type not in ['story', 'bug', 'task', 'epic']:
        issue_type = 'task'

    story_points = 1
    story_points_str = request.POST.get('story_points')
    if story_points_str:
        try:
            story_points = int(story_points_str)
        except ValueError:
            pass

    labels = request.POST.get('labels', '').strip()
    epic_name = request.POST.get('epic_name', '').strip()
    sprint_name = request.POST.get('sprint_name', 'Sprint 1').strip() or 'Sprint 1'

    assignee_id = request.POST.get('assignee')
    assignee = None
    if assignee_id:
        try:
            assignee = User.objects.get(id=assignee_id)
        except User.DoesNotExist:
            pass

    due_date_str = request.POST.get('due_date')
    due_date = None
    if due_date_str:
        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    if not title:
        messages.error(request, "Task title cannot be empty.")
        return redirect(f"/project/{slug}/?tab=management")

    task = ProjectTask.objects.create(
        project=project,
        title=title,
        description=description,
        status=status,
        priority=priority,
        issue_type=issue_type,
        story_points=story_points,
        labels=labels,
        epic_name=epic_name,
        sprint_name=sprint_name,
        assignee=assignee,
        created_by=current_user,
        due_date=due_date
    )

    messages.success(request, f"Card '{task.title}' created!")

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        assignee_name = task.assignee.get_full_name() or task.assignee.username if task.assignee else 'Unassigned'
        assignee_initials = task.assignee.profile.initials if task.assignee and hasattr(task.assignee, 'profile') else 'NA'
        assignee_color = task.assignee.profile.avatar_color if task.assignee and hasattr(task.assignee, 'profile') else '#6B778C'
        return JsonResponse({
            'status': 'ok',
            'task_id': task.id,
            'title': task.title,
            'description': task.description,
            'card_status': task.status,
            'priority': task.priority,
            'issue_type': task.issue_type,
            'assignee_name': assignee_name,
            'assignee_initials': assignee_initials,
            'assignee_color': assignee_color,
            'due_date': task.due_date.strftime('%b %d') if task.due_date else None,
        })

    return redirect(f"/project/{slug}/?tab=management")


@require_POST
@login_required(login_url='login')
def update_task_status(request, task_id):
    task = get_object_or_404(ProjectTask, id=task_id)
    new_status = request.POST.get('status', '').strip()

    # Validate against project's columns
    valid_cols = list(task.project.kanban_columns.values_list('slug', flat=True))
    if new_status in valid_cols or new_status in ['todo', 'inprogress', 'done']:
        task.status = new_status
        task.save(update_fields=['status', 'updated_at'])
        return JsonResponse({
            'status': 'ok',
            'task_id': task.id,
            'new_status': task.status,
            'status_display': task.get_status_display()
        })

    return JsonResponse({'status': 'error', 'message': 'Invalid column/status'}, status=400)


@require_POST
@login_required(login_url='login')
def delete_task(request, task_id):
    task = get_object_or_404(ProjectTask, id=task_id)
    project_slug = task.project.slug
    task_title = task.title
    task.delete()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok', 'task_id': task_id})

    messages.info(request, f"Task '{task_title}' deleted.")
    return redirect(f"/project/{project_slug}/?tab=management")


@require_POST
@login_required(login_url='login')
def edit_task(request, task_id):
    task = get_object_or_404(ProjectTask, id=task_id)

    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    status = request.POST.get('status', '').strip()
    
    valid_cols = list(task.project.kanban_columns.values_list('slug', flat=True))
    if status in valid_cols or status in ['todo', 'inprogress', 'done']:
        task.status = status

    priority = request.POST.get('priority', '').strip().lower()
    if priority not in ['low', 'medium', 'high', 'urgent', 'critical']:
        priority = task.priority
    issue_type = request.POST.get('issue_type', '').strip().lower()
    if issue_type not in ['story', 'bug', 'task', 'epic']:
        issue_type = task.issue_type

    story_points_str = request.POST.get('story_points')
    if story_points_str is not None and story_points_str != '':
        try:
            task.story_points = int(story_points_str)
        except ValueError:
            pass

    labels = request.POST.get('labels')
    if labels is not None:
        task.labels = labels.strip()

    epic_name = request.POST.get('epic_name')
    if epic_name is not None:
        task.epic_name = epic_name.strip()

    sprint_name = request.POST.get('sprint_name')
    if sprint_name is not None:
        task.sprint_name = sprint_name.strip()

    assignee_id = request.POST.get('assignee')
    if assignee_id is not None:
        if assignee_id == '':
            task.assignee = None
        else:
            try:
                task.assignee = User.objects.get(id=assignee_id)
            except User.DoesNotExist:
                pass

    reporter_id = request.POST.get('reporter')
    if reporter_id:
        try:
            task.reporter = User.objects.get(id=reporter_id)
        except User.DoesNotExist:
            pass

    due_date_str = request.POST.get('due_date')
    if due_date_str is not None:
        if due_date_str == '':
            task.due_date = None
        else:
            try:
                task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

    start_date_str = request.POST.get('start_date')
    if start_date_str is not None:
        if start_date_str == '':
            task.start_date = None
        else:
            try:
                task.start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

    if not title:
        return JsonResponse({'status': 'error', 'message': 'Title is required'}, status=400)

    task.title = title
    task.description = description
    task.priority = priority
    task.issue_type = issue_type
    task.save()

    assignee_name = task.assignee.get_full_name() or task.assignee.username if task.assignee else 'Unassigned'
    assignee_initials = task.assignee.profile.initials if task.assignee and hasattr(task.assignee, 'profile') else 'NA'
    assignee_color = task.assignee.profile.avatar_color if task.assignee and hasattr(task.assignee, 'profile') else '#6B778C'

    return JsonResponse({
        'status': 'ok',
        'task_id': task.id,
        'title': task.title,
        'description': task.description,
        'card_status': task.status,
        'priority': task.priority,
        'issue_type': task.issue_type,
        'story_points': task.story_points,
        'labels': task.labels,
        'epic_name': task.epic_name,
        'sprint_name': task.sprint_name,
        'assignee_name': assignee_name,
        'assignee_id': task.assignee.id if task.assignee else '',
        'assignee_initials': assignee_initials,
        'assignee_color': assignee_color,
        'due_date': task.due_date.strftime('%Y-%m-%d') if task.due_date else '',
        'due_date_display': task.due_date.strftime('%b %d') if task.due_date else '',
        'start_date': task.start_date.strftime('%Y-%m-%d') if task.start_date else '',
    })


@require_POST
@login_required(login_url='login')
def add_task_comment(request, task_id):
    from .models import TaskComment
    task = get_object_or_404(ProjectTask, id=task_id)
    content = request.POST.get('content', '').strip()
    if not content:
        return JsonResponse({'status': 'error', 'message': 'Comment cannot be empty'}, status=400)

    comment = TaskComment.objects.create(
        task=task,
        author=request.user,
        content=content
    )

    return JsonResponse({
        'status': 'ok',
        'comment_id': comment.id,
        'author': request.user.get_full_name() or request.user.username,
        'author_initials': request.user.profile.initials if hasattr(request.user, 'profile') else 'U',
        'author_color': request.user.profile.avatar_color if hasattr(request.user, 'profile') else '#1264A3',
        'content': comment.content,
        'created_at': comment.created_at.strftime('%b %d, %H:%M'),
    })


@login_required(login_url='login')
def get_task_comments(request, task_id):
    from .models import TaskComment
    task = get_object_or_404(ProjectTask, id=task_id)
    comments = TaskComment.objects.filter(task=task).select_related('author', 'author__profile').order_by('created_at')

    data = []
    for c in comments:
        data.append({
            'id': c.id,
            'author': c.author.get_full_name() or c.author.username if c.author else 'Unknown',
            'author_initials': c.author.profile.initials if c.author and hasattr(c.author, 'profile') else 'U',
            'author_color': c.author.profile.avatar_color if c.author and hasattr(c.author, 'profile') else '#1264A3',
            'content': c.content,
            'created_at': c.created_at.strftime('%b %d, %H:%M'),
        })

    return JsonResponse({'status': 'ok', 'comments': data})


# ==============================================================================
# JIRA KANBAN COLUMN MANAGEMENT VIEWS (Add, Rename, Reorder, Delete Column)
# ==============================================================================

@require_POST
@login_required(login_url='login')
def add_kanban_column(request, slug):
    project = get_object_or_404(Project, slug=slug)
    name = request.POST.get('name', '').strip()
    color = request.POST.get('color', '#0052CC').strip() or '#0052CC'

    if not name:
        return JsonResponse({'status': 'error', 'message': 'Column title cannot be empty.'}, status=400)

    from django.utils.text import slugify
    col_slug = slugify(name)
    if not col_slug:
        col_slug = f"col-{project.kanban_columns.count() + 1}"

    # Ensure unique slug within this project
    existing = project.kanban_columns.filter(slug=col_slug).first()
    if existing:
        col_slug = f"{col_slug}-{project.kanban_columns.count() + 1}"

    max_order = project.kanban_columns.aggregate(models.Max('order'))['order__max']
    new_order = (max_order + 1) if max_order is not None else 0

    column = KanbanColumn.objects.create(
        project=project,
        name=name,
        slug=col_slug,
        color=color,
        order=new_order
    )

    return JsonResponse({
        'status': 'ok',
        'column_id': column.id,
        'name': column.name,
        'slug': column.slug,
        'color': column.color,
        'order': column.order
    })


@require_POST
@login_required(login_url='login')
def rename_kanban_column(request, column_id):
    column = get_object_or_404(KanbanColumn, id=column_id)
    name = request.POST.get('name', '').strip()
    color = request.POST.get('color', '').strip()

    if not name:
        return JsonResponse({'status': 'error', 'message': 'Column title cannot be empty.'}, status=400)

    column.name = name
    if color:
        column.color = color
    column.save()

    return JsonResponse({
        'status': 'ok',
        'column_id': column.id,
        'name': column.name,
        'color': column.color
    })


@require_POST
@login_required(login_url='login')
def reorder_kanban_column(request, column_id):
    column = get_object_or_404(KanbanColumn, id=column_id)
    direction = request.POST.get('direction', 'right') # 'left' or 'right'

    columns = list(column.project.kanban_columns.order_by('order', 'id'))
    try:
        idx = [c.id for c in columns].index(column.id)
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Column not found'}, status=400)

    if direction == 'left' and idx > 0:
        columns[idx], columns[idx - 1] = columns[idx - 1], columns[idx]
    elif direction == 'right' and idx < len(columns) - 1:
        columns[idx], columns[idx + 1] = columns[idx + 1], columns[idx]
    else:
        return JsonResponse({'status': 'ok', 'message': 'No movement'})

    for i, col in enumerate(columns):
        if col.order != i:
            col.order = i
            col.save(update_fields=['order'])

    return JsonResponse({'status': 'ok'})


@require_POST
@login_required(login_url='login')
def delete_kanban_column(request, column_id):
    column = get_object_or_404(KanbanColumn, id=column_id)
    project = column.project

    # Move any cards in this column to the first remaining column
    other_col = project.kanban_columns.exclude(id=column.id).first()
    fallback_slug = other_col.slug if other_col else 'todo'
    project.tasks.filter(status=column.slug).update(status=fallback_slug)

    column.delete()
    return JsonResponse({'status': 'ok', 'fallback_status': fallback_slug})


# ==============================================================================
# DATA ANALYTICS & EXCEL EXPORT
# ==============================================================================

@login_required(login_url='login')
def analytics_dashboard(request):
    current_user = request.user

    # 1. KPI Metrics
    total_projects = Project.objects.count()
    total_reports = DailyReport.objects.count()
    total_users = User.objects.count()
    total_tagged = DailyReport.tagged_users.through.objects.count()
    total_reactions = ReportReaction.objects.count()
    total_comments = ReportComment.objects.count()

    # 2. Project Activity (Reports per project)
    projects = Project.objects.annotate(report_count=Count('reports')).order_by('-report_count')
    project_names = [f"#{p.name}" for p in projects]
    project_counts = [p.report_count for p in projects]

    # 3. Top Active Contributors
    top_authors = User.objects.annotate(report_count=Count('daily_reports')).filter(report_count__gt=0).order_by('-report_count')[:7]
    author_names = [u.get_full_name() or u.username for u in top_authors]
    author_counts = [u.report_count for u in top_authors]

    # 4. Most Tagged Teammates
    top_tagged = User.objects.annotate(tag_count=Count('tagged_in_reports')).filter(tag_count__gt=0).order_by('-tag_count')[:7]
    tagged_names = [u.get_full_name() or u.username for u in top_tagged]
    tagged_counts = [u.tag_count for u in top_tagged]

    # 5. Daily Activity Timeline
    timeline_qs = DailyReport.objects.values('date').annotate(count=Count('id')).order_by('date')
    timeline_labels = [entry['date'].strftime('%b %d') for entry in timeline_qs]
    timeline_data = [entry['count'] for entry in timeline_qs]

    # 6. Spreadsheet Data Table (all updates)
    all_reports_list = DailyReport.objects.select_related('author', 'author__profile', 'project').prefetch_related('tagged_users', 'comments', 'reactions').order_by('-date', '-created_at')

    context = {
        'total_projects': total_projects,
        'total_reports': total_reports,
        'total_users': total_users,
        'total_tagged': total_tagged,
        'total_reactions': total_reactions,
        'total_comments': total_comments,
        'project_names': project_names,
        'project_counts': project_counts,
        'author_names': author_names,
        'author_counts': author_counts,
        'tagged_names': tagged_names,
        'tagged_counts': tagged_counts,
        'timeline_labels': timeline_labels,
        'timeline_data': timeline_data,
        'all_reports_list': all_reports_list,
        'current_user': current_user,
    }
    return render(request, 'analytics.html', context)


@login_required(login_url='login')
def export_excel(request):
    """Generates and downloads a complete Excel workbook (.xlsx) of all workspace data"""
    wb = openpyxl.Workbook()

    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='3F0E40', end_color='3F0E40', fill_type='solid')
    sub_header_fill = PatternFill(start_color='1264A3', end_color='1264A3', fill_type='solid')
    border_thin = Border(
        left=Side(style='thin', color='E0E0E0'),
        right=Side(style='thin', color='E0E0E0'),
        top=Side(style='thin', color='E0E0E0'),
        bottom=Side(style='thin', color='E0E0E0')
    )
    align_center = Alignment(horizontal='center', vertical='center')
    align_left = Alignment(horizontal='left', vertical='center', wrap_text=True)

    # SHEET 1: Daily Updates & Messages
    ws1 = wb.active
    ws1.title = "Workspace Updates & DSR"

    headers1 = [
        "ID", "Date", "Project Channel", "Author", "Role",
        "Update / Message Content", "Tagged People", "Comments Count", "Reactions Count", "Posted At"
    ]
    ws1.append(headers1)
    for cell in ws1[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center

    reports = DailyReport.objects.select_related('author', 'author__profile', 'project').prefetch_related('tagged_users', 'comments', 'reactions').order_by('-date', '-created_at')
    for r in reports:
        tagged_str = ", ".join([f"@{tu.username}" for tu in r.tagged_users.all()]) or "None"
        content_text = r.content if r.content else f"Yesterday: {r.yesterday_work} | Today: {r.today_plan} | Blockers: {r.blockers or 'None'}"
        ws1.append([
            r.id,
            r.date.strftime('%Y-%m-%d'),
            f"#{r.project.name}",
            r.author.get_full_name() or r.author.username,
            r.author.profile.role if hasattr(r.author, 'profile') else 'Member',
            content_text,
            tagged_str,
            r.comments.count(),
            r.reactions.count(),
            r.created_at.strftime('%Y-%m-%d %H:%M')
        ])

    for row in ws1.iter_rows(min_row=2):
        for cell in row:
            cell.border = border_thin
            if cell.column in [1, 2, 8, 9, 10]:
                cell.alignment = align_center
            else:
                cell.alignment = align_left

    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 50)

    # SHEET 2: Projects Overview
    ws2 = wb.create_sheet(title="Projects Progress")
    headers2 = ["Project Name", "Description", "Created By", "Members Count", "Total Updates Posted", "Created Date"]
    ws2.append(headers2)
    for cell in ws2[1]:
        cell.font = header_font
        cell.fill = sub_header_fill
        cell.alignment = align_center

    for p in Project.objects.annotate(report_count=Count('reports')).order_by('-report_count'):
        ws2.append([
            f"#{p.name}",
            p.description or "No description",
            p.created_by.get_full_name() if p.created_by else 'Admin',
            p.members.count(),
            p.report_count,
            p.created_at.strftime('%Y-%m-%d')
        ])
    for row in ws2.iter_rows(min_row=2):
        for cell in row:
            cell.border = border_thin
            cell.alignment = align_left if cell.column <= 3 else align_center

    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = min(max(max_len + 3, 15), 45)

    # SHEET 3: Team Members & Tagging Stats
    ws3 = wb.create_sheet(title="Team Analytics & Tagging")
    headers3 = ["Full Name", "Username", "Email", "Job Title", "Department", "Updates Posted", "Times Tagged"]
    ws3.append(headers3)
    for cell in ws3[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center

    for u in User.objects.select_related('profile').annotate(
        reports_count=Count('daily_reports'),
        tagged_count=Count('tagged_in_reports')
    ).order_by('-reports_count'):
        ws3.append([
            u.get_full_name() or u.username,
            f"@{u.username}",
            u.email or "N/A",
            u.profile.role if hasattr(u, 'profile') else 'Member',
            u.profile.department if hasattr(u, 'profile') else 'General',
            u.reports_count,
            u.tagged_count
        ])
    for row in ws3.iter_rows(min_row=2):
        for cell in row:
            cell.border = border_thin
            cell.alignment = align_left if cell.column <= 5 else align_center

    for col in ws3.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws3.column_dimensions[col_letter].width = min(max(max_len + 3, 14), 35)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"statuspulse_analytics_{timezone.now().strftime('%Y%m%d_%H%M')}.xlsx"
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required(login_url='login')
def export_project_excel(request, slug):
    """Generates and downloads an Excel workbook (.xlsx) specifically for the current project channel"""
    project = get_object_or_404(Project, slug=slug)
    wb = openpyxl.Workbook()

    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='0052CC', end_color='0052CC', fill_type='solid') # Atlassian Jira Blue
    sub_header_fill = PatternFill(start_color='172B4D', end_color='172B4D', fill_type='solid') # Dark Navy
    teal_header_fill = PatternFill(start_color='00875A', end_color='00875A', fill_type='solid') # Success Green
    border_thin = Border(
        left=Side(style='thin', color='DFE1E6'),
        right=Side(style='thin', color='DFE1E6'),
        top=Side(style='thin', color='DFE1E6'),
        bottom=Side(style='thin', color='DFE1E6')
    )
    align_center = Alignment(horizontal='center', vertical='center')
    align_left = Alignment(horizontal='left', vertical='center', wrap_text=True)

    # ----------------------------------------------------
    # SHEET 1: Kanban Tasks & Jira Board
    # ----------------------------------------------------
    ws1 = wb.active
    ws1.title = "Tasks & Kanban Board"

    headers1 = [
        "Task ID", "Issue Type", "Title", "Status / Column", "Priority",
        "Assignee", "Reporter", "Due Date", "Start Date",
        "Epic", "Labels", "Description", "Created At"
    ]
    ws1.append(headers1)
    for cell in ws1[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center

    col_map = {c.slug: c.name for c in project.kanban_columns.all()}

    tasks = list(project.tasks.select_related('assignee', 'assignee__profile', 'reporter', 'reporter__profile', 'created_by').order_by('id'))
    for t in tasks:
        task_code = f"#{project.slug[:4].upper()}-{t.id}"
        col_name = col_map.get(t.status, t.status.replace('-', ' ').title())
        assignee_name = (t.assignee.get_full_name() or t.assignee.username) if t.assignee else "Unassigned"
        reporter_name = (t.reporter.get_full_name() or t.reporter.username) if t.reporter else ((t.created_by.get_full_name() or t.created_by.username) if t.created_by else "System")

        ws1.append([
            task_code,
            (t.issue_type or 'task').capitalize(),
            t.title,
            col_name,
            t.priority.capitalize(),
            assignee_name,
            reporter_name,
            t.due_date.strftime('%Y-%m-%d') if t.due_date else "None",
            t.start_date.strftime('%Y-%m-%d') if t.start_date else "None",
            t.epic_name or "None",
            t.labels or "None",
            t.description or "",
            t.created_at.strftime('%Y-%m-%d %H:%M')
        ])

    for row in ws1.iter_rows(min_row=2):
        for cell in row:
            cell.border = border_thin
            if cell.column in [1, 2, 4, 5, 8, 9, 13]:
                cell.alignment = align_center
            else:
                cell.alignment = align_left

    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    # ----------------------------------------------------
    # SHEET 2: Channel Status Reports & Confluence DSR
    # ----------------------------------------------------
    ws2 = wb.create_sheet(title="Status Updates & DSR")
    headers2 = [
        "Report ID", "Date", "Author", "Role",
        "What Done Today / Work Details", "Issues Faced / Blockers",
        "Needed From Other End", "Tagged Members", "Comments Count", "Reactions Count", "Posted At"
    ]
    ws2.append(headers2)
    for cell in ws2[1]:
        cell.font = header_font
        cell.fill = sub_header_fill
        cell.alignment = align_center

    reports_qs = DailyReport.objects.filter(project=project).select_related('author', 'author__profile').prefetch_related('tagged_users', 'comments', 'reactions').order_by('-date', '-created_at')
    reports = list(reports_qs)
    for r in reports:
        tagged_str = ", ".join([f"@{tu.username}" for tu in r.tagged_users.all()]) or "None"
        work_done = r.what_done_today or r.yesterday_work or r.content or "None"
        issues = r.issues_faced or r.blockers or "None"
        needed = r.needed_from_others or r.today_plan or "None"

        ws2.append([
            r.id,
            r.date.strftime('%Y-%m-%d'),
            r.author.get_full_name() or r.author.username,
            r.author.profile.role if hasattr(r.author, 'profile') else 'Member',
            work_done,
            issues,
            needed,
            tagged_str,
            r.comments.count(),
            r.reactions.count(),
            r.created_at.strftime('%Y-%m-%d %H:%M')
        ])

    for row in ws2.iter_rows(min_row=2):
        for cell in row:
            cell.border = border_thin
            if cell.column in [1, 2, 4, 9, 10, 11]:
                cell.alignment = align_center
            else:
                cell.alignment = align_left

    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    # ----------------------------------------------------
    # SHEET 3: Team Workload & Contribution
    # ----------------------------------------------------
    ws3 = wb.create_sheet(title="Team Workload")
    headers3 = [
        "Full Name", "Username", "Role", "Email",
        "Assigned Tasks", "Completed Tasks", "Open Tasks",
        "DSR Updates Posted"
    ]
    ws3.append(headers3)
    for cell in ws3[1]:
        cell.font = header_font
        cell.fill = teal_header_fill
        cell.alignment = align_center

    for member in project.members.all().select_related('profile'):
        assigned_tasks = [t for t in tasks if t.assignee_id == member.id]
        completed_tasks = [t for t in assigned_tasks if t.status == 'done']
        open_tasks = len(assigned_tasks) - len(completed_tasks)
        reports_count = len([r for r in reports if r.author_id == member.id])

        ws3.append([
            member.get_full_name() or member.username,
            f"@{member.username}",
            member.profile.role if hasattr(member, 'profile') else 'Member',
            member.email or "N/A",
            len(assigned_tasks),
            len(completed_tasks),
            open_tasks,
            reports_count
        ])

    for row in ws3.iter_rows(min_row=2):
        for cell in row:
            cell.border = border_thin
            if cell.column in [2, 5, 6, 7, 8]:
                cell.alignment = align_center
            else:
                cell.alignment = align_left

    for col in ws3.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws3.column_dimensions[col_letter].width = min(max(max_len + 3, 14), 35)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"{project.slug}_analytics_{timezone.now().strftime('%Y%m%d_%H%M')}.xlsx"
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ==============================================================================
# JIRA TASK MODAL API & SUBTASKS (FASTSPORTS STYLE)
# ==============================================================================

@login_required(login_url='login')
def get_task_details(request, task_id):
    task = get_object_or_404(
        ProjectTask.objects.select_related('project', 'assignee', 'assignee__profile', 'reporter', 'reporter__profile', 'created_by', 'created_by__profile'),
        id=task_id
    )

    def human_time(dt):
        if not dt:
            return ""
        diff = timezone.now() - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            mins = max(1, seconds // 60)
            return f"{mins} minute{'s' if mins > 1 else ''} ago"
        elif seconds < 86400:
            hours = max(1, seconds // 3600)
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif seconds < 604800:
            days = max(1, seconds // 86400)
            return f"{days} day{'s' if days > 1 else ''} ago"
        elif seconds < 31536000:
            months = max(1, seconds // 2592000)
            return f"{months} month{'s' if months > 1 else ''} ago"
        else:
            years = max(1, seconds // 31536000)
            return f"{years} year{'s' if years > 1 else ''} ago"

    columns_data = []
    for col in task.project.kanban_columns.order_by('order', 'id'):
        columns_data.append({
            'id': col.id,
            'name': col.name,
            'slug': col.slug,
            'color': col.color,
            'is_current': (col.slug == task.status)
        })

    subtasks_data = []
    for s in task.subtasks.all():
        subtasks_data.append({
            'id': s.id,
            'title': s.title,
            'is_completed': s.is_completed,
        })

    attachments_data = []
    for a in task.attachments.all():
        attachments_data.append({
            'id': a.id,
            'filename': a.filename or (a.file.name.split('/')[-1] if a.file else 'Attachment'),
            'file_url': a.file.url if a.file else '#',
            'created_at': human_time(a.created_at)
        })

    comments_data = []
    for c in task.comments.select_related('author', 'author__profile').order_by('-created_at'):
        comments_data.append({
            'id': c.id,
            'author': c.author.get_full_name() or c.author.username if c.author else 'Unknown',
            'author_username': c.author.username if c.author else '',
            'author_initials': c.author.profile.initials if c.author and hasattr(c.author, 'profile') else 'U',
            'author_color': c.author.profile.avatar_color if c.author and hasattr(c.author, 'profile') else '#1264A3',
            'content': c.content,
            'created_at': human_time(c.created_at)
        })

    members_data = []
    for m in task.project.members.select_related('profile'):
        members_data.append({
            'id': m.id,
            'name': m.get_full_name() or m.username,
            'username': m.username,
            'role': m.profile.role if hasattr(m, 'profile') else 'Member',
            'initials': m.profile.initials if hasattr(m, 'profile') else 'U',
            'avatar_color': m.profile.avatar_color if hasattr(m, 'profile') else '#1264A3',
        })

    priority_labels = {
        'critical': 'Highest',
        'urgent': 'Highest',
        'high': 'High',
        'medium': 'Medium',
        'low': 'Low'
    }

    reporter_user = task.reporter or task.created_by or request.user
    current_col = task.project.kanban_columns.filter(slug=task.status).first()
    status_display_name = current_col.name if current_col else task.status.replace('-', ' ').title()

    return JsonResponse({
        'status': 'ok',
        'task': {
            'id': task.id,
            'key': f"{task.project.name[:3].upper()}-{task.id}",
            'title': task.title,
            'description': task.description or '',
            'status': task.status,
            'status_name': status_display_name,
            'priority': task.priority,
            'priority_display': priority_labels.get(task.priority.lower(), task.priority.capitalize()),
            'issue_type': task.issue_type,
            'labels': task.labels or '',
            'epic_name': task.epic_name or '',
            'due_date': task.due_date.strftime('%Y-%m-%d') if task.due_date else '',
            'created_at_relative': human_time(task.created_at),
            'updated_at_relative': human_time(task.updated_at),
            'assignee': {
                'id': task.assignee.id,
                'name': task.assignee.get_full_name() or task.assignee.username,
                'username': task.assignee.username,
                'initials': task.assignee.profile.initials if hasattr(task.assignee, 'profile') else 'UN',
                'avatar_color': task.assignee.profile.avatar_color if hasattr(task.assignee, 'profile') else '#E65100',
            } if task.assignee else None,
            'reporter': {
                'id': reporter_user.id,
                'name': reporter_user.get_full_name() or reporter_user.username,
                'username': reporter_user.username,
                'initials': reporter_user.profile.initials if hasattr(reporter_user, 'profile') else 'RP',
                'avatar_color': reporter_user.profile.avatar_color if hasattr(reporter_user, 'profile') else '#42526E',
            } if reporter_user else None,
            'columns': columns_data,
            'subtasks': subtasks_data,
            'attachments': attachments_data,
            'comments': comments_data,
            'members': members_data,
        }
    })


@require_POST
@login_required(login_url='login')
def quick_update_task_field(request, task_id):
    task = get_object_or_404(ProjectTask, id=task_id)
    field = request.POST.get('field', '').strip()
    value = request.POST.get('value', '').strip()

    if field == 'title':
        if not value:
            return JsonResponse({'status': 'error', 'message': 'Title cannot be empty.'}, status=400)
        task.title = value
        task.save(update_fields=['title', 'updated_at'])
    elif field == 'description':
        task.description = value
        task.save(update_fields=['description', 'updated_at'])
    elif field == 'status':
        valid_cols = list(task.project.kanban_columns.values_list('slug', flat=True))
        if value in valid_cols or value in ['todo', 'inprogress', 'done']:
            task.status = value
            task.save(update_fields=['status', 'updated_at'])
    elif field == 'priority':
        if value in ['low', 'medium', 'high', 'urgent', 'critical']:
            task.priority = value
            task.save(update_fields=['priority', 'updated_at'])
    elif field == 'assignee':
        if value == '' or value == '0':
            task.assignee = None
        else:
            try:
                task.assignee = User.objects.get(id=int(value))
            except (User.DoesNotExist, ValueError):
                pass
        task.save(update_fields=['assignee', 'updated_at'])
    elif field == 'reporter':
        if value:
            try:
                task.reporter = User.objects.get(id=int(value))
                task.save(update_fields=['reporter', 'updated_at'])
            except (User.DoesNotExist, ValueError):
                pass
    elif field == 'labels':
        task.labels = value
        task.save(update_fields=['labels', 'updated_at'])
    elif field == 'due_date':
        if not value:
            task.due_date = None
        else:
            try:
                task.due_date = datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                pass
        task.save(update_fields=['due_date', 'updated_at'])

    priority_labels = {'critical': 'Highest', 'urgent': 'Highest', 'high': 'High', 'medium': 'Medium', 'low': 'Low'}
    current_col = task.project.kanban_columns.filter(slug=task.status).first()

    return JsonResponse({
        'status': 'ok',
        'task_id': task.id,
        'field': field,
        'value': value,
        'status': task.status,
        'status_name': current_col.name if current_col else task.status.replace('-', ' ').title(),
        'assignee_name': (task.assignee.get_full_name() or task.assignee.username) if task.assignee else 'Unassigned',
        'assignee_initials': task.assignee.profile.initials if task.assignee and hasattr(task.assignee, 'profile') else 'UN',
        'assignee_color': task.assignee.profile.avatar_color if task.assignee and hasattr(task.assignee, 'profile') else '#E65100',
        'reporter_name': (task.reporter.get_full_name() or task.reporter.username) if task.reporter else 'Unassigned',
        'reporter_initials': task.reporter.profile.initials if task.reporter and hasattr(task.reporter, 'profile') else 'RP',
        'reporter_color': task.reporter.profile.avatar_color if task.reporter and hasattr(task.reporter, 'profile') else '#42526E',
        'priority': task.priority,
        'priority_display': priority_labels.get(task.priority.lower(), task.priority.capitalize()),
        'title': task.title,
        'description': task.description,
        'labels': task.labels,
    })


@require_POST
@login_required(login_url='login')
def add_subtask(request, task_id):
    task = get_object_or_404(ProjectTask, id=task_id)
    title = request.POST.get('title', '').strip()
    if not title:
        return JsonResponse({'status': 'error', 'message': 'Subtask title cannot be empty.'}, status=400)
    subtask = TaskSubtask.objects.create(task=task, title=title)
    return JsonResponse({
        'status': 'ok',
        'subtask': {
            'id': subtask.id,
            'title': subtask.title,
            'is_completed': subtask.is_completed
        }
    })


@require_POST
@login_required(login_url='login')
def toggle_subtask(request, subtask_id):
    subtask = get_object_or_404(TaskSubtask, id=subtask_id)
    subtask.is_completed = not subtask.is_completed
    subtask.save(update_fields=['is_completed'])
    return JsonResponse({
        'status': 'ok',
        'subtask_id': subtask.id,
        'is_completed': subtask.is_completed
    })


@require_POST
@login_required(login_url='login')
def delete_subtask(request, subtask_id):
    subtask = get_object_or_404(TaskSubtask, id=subtask_id)
    subtask.delete()
    return JsonResponse({'status': 'ok'})


@require_POST
@login_required(login_url='login')
def upload_task_attachment(request, task_id):
    task = get_object_or_404(ProjectTask, id=task_id)
    upload = request.FILES.get('file')
    filename = request.POST.get('filename', '').strip()
    if not upload and not filename:
        return JsonResponse({'status': 'error', 'message': 'No file provided'}, status=400)

    fn = filename or (upload.name if upload else 'Attachment')
    attachment = TaskAttachment.objects.create(
        task=task,
        file=upload,
        filename=fn,
        uploaded_by=request.user
    )
    return JsonResponse({
        'status': 'ok',
        'attachment': {
            'id': attachment.id,
            'filename': attachment.filename,
            'file_url': attachment.file.url if attachment.file else '#'
        }
    })

@require_POST
@login_required(login_url='login')
def update_confluence_header(request, project_slug):
    project = get_object_or_404(Project, slug=project_slug)
    page_title = request.POST.get('confluence_page_title', '').strip()
    team_name = request.POST.get('team_name', '').strip()
    supervisor = request.POST.get('supervisor', '').strip()

    if page_title:
        project.confluence_page_title = page_title
    if team_name:
        project.team_name = team_name
    if supervisor:
        project.supervisor = supervisor

    project.save(update_fields=['confluence_page_title', 'team_name', 'supervisor'])

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({
            'status': 'ok',
            'confluence_page_title': project.confluence_page_title or f"{project.name.upper()} Project 3rd Sept week 2026",
            'team_name': project.team_name or 'Team MSGSWITCH',
            'supervisor': project.supervisor or 'Girish S, Dinesh Naik',
        })

    messages.success(request, 'Confluence document details updated successfully!')
    # redirect back to referrer or project_detail
    return redirect(request.META.get('HTTP_REFERER', 'project_detail'))


@require_POST
@login_required(login_url='login')
def edit_daily_report(request, report_id):
    report = get_object_or_404(DailyReport, id=report_id)
    # Check permissions: author, project creator, or staff
    if report.author != request.user and not request.user.is_staff and report.project.created_by != request.user:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        messages.error(request, 'You do not have permission to edit this message.')
        return redirect(request.META.get('HTTP_REFERER', 'project_detail'))

    content = request.POST.get('content')
    priority = request.POST.get('priority', '').strip()
    yesterday_work = request.POST.get('yesterday_work', '').strip()
    today_plan = request.POST.get('today_plan', '').strip()
    blockers = request.POST.get('blockers', '').strip()
    links_notes = request.POST.get('links_notes', '').strip()

    if content is not None:
        report.content = content.strip()
        auto_tag_mentions(report, report.content)
    if priority is not None and priority != '':
        report.priority = priority
    if yesterday_work is not None and yesterday_work != '':
        report.yesterday_work = yesterday_work
        report.what_done_today = yesterday_work
    if today_plan is not None and today_plan != '':
        report.today_plan = today_plan
    if blockers is not None and blockers != '':
        report.blockers = blockers
    if links_notes is not None and links_notes != '':
        report.links_notes = links_notes

    report.save()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({
            'status': 'ok',
            'report_id': report.id,
            'content': report.content,
            'message_html': report.message_html,
            'priority': report.priority,
            'yesterday_work': report.yesterday_work,
            'yesterday_work_html': report.yesterday_work_html,
            'today_plan': report.today_plan,
            'today_plan_html': report.today_plan_html,
            'blockers': report.blockers,
            'has_blockers': report.has_blockers,
            'links_notes': report.links_notes,
        })

    messages.success(request, 'Message updated successfully!')
    return redirect(request.META.get('HTTP_REFERER', 'project_detail'))


@require_POST
@login_required(login_url='login')
def delete_daily_report(request, report_id):
    report = get_object_or_404(DailyReport, id=report_id)
    # Check permissions: author, project creator, or staff
    if report.author != request.user and not request.user.is_staff and report.project.created_by != request.user:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        messages.error(request, 'You do not have permission to delete this message.')
        return redirect(request.META.get('HTTP_REFERER', 'project_detail'))

    project_slug = report.project.slug
    report.delete()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'status': 'ok', 'report_id': report_id})

    messages.success(request, 'Message deleted successfully.')
    return redirect(request.META.get('HTTP_REFERER', 'project_detail'))


@require_POST
@login_required(login_url='login')
def edit_comment(request, comment_id):
    comment = get_object_or_404(ReportComment, id=comment_id)
    if comment.author != request.user and not request.user.is_staff and comment.report.project.created_by != request.user:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        messages.error(request, 'Permission denied.')
        return redirect(request.META.get('HTTP_REFERER', 'project_detail'))

    message = request.POST.get('message', '').strip()
    if message:
        comment.message = message
        comment.save()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'status': 'ok', 'comment_id': comment.id, 'message': comment.message})

    messages.success(request, 'Reply updated.')
    return redirect(request.META.get('HTTP_REFERER', 'project_detail'))


@require_POST
@login_required(login_url='login')
def delete_comment(request, comment_id):
    comment = get_object_or_404(ReportComment, id=comment_id)
    if comment.author != request.user and not request.user.is_staff and comment.report.project.created_by != request.user:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        messages.error(request, 'Permission denied.')
        return redirect(request.META.get('HTTP_REFERER', 'project_detail'))

    comment_id_val = comment.id
    comment.delete()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'status': 'ok', 'comment_id': comment_id_val})

    messages.success(request, 'Reply deleted.')
    return redirect(request.META.get('HTTP_REFERER', 'project_detail'))


@require_POST
@login_required(login_url='login')
def add_confluence_section(request, slug):
    project = get_object_or_404(Project, slug=slug)
    date_str = request.POST.get('date', '').strip()
    custom_title = request.POST.get('custom_title', '').strip()

    if not date_str:
        messages.error(request, 'Date is required.')
        return redirect('project_detail', slug=slug)

    try:
        parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, 'Invalid date format.')
        return redirect('project_detail', slug=slug)

    sec, created = ProjectConfluenceSection.objects.get_or_create(
        project=project,
        date=parsed_date,
        defaults={'custom_title': custom_title}
    )
    if not created and custom_title:
        sec.custom_title = custom_title
        sec.save()

    messages.success(request, f"Added date section {sec.display_title} to Table of Contents!")
    return redirect(f"/project/{slug}/#confluence-{sec.anchor}")


@require_POST
@login_required(login_url='login')
def delete_confluence_section(request, section_id):
    section = get_object_or_404(ProjectConfluenceSection, id=section_id)
    project_slug = section.project.slug
    section.delete()
    messages.info(request, "Removed date section from Table of Contents.")
    return redirect('project_detail', slug=project_slug)




# ==============================================================================
# HUDDLE (AUDIO / VIDEO MEETING) VIEWS
# ==============================================================================

@login_required(login_url='login')
def huddle_status(request, slug):
    """Returns active huddle state, participants, and whether current user is in it."""
    project = get_object_or_404(Project, slug=slug)
    huddle = Huddle.objects.filter(project=project, is_active=True).first()

    if not huddle:
        return JsonResponse({'is_active': False})

    # Auto-expire participants who haven't pinged in 45 seconds
    cutoff = timezone.now() - timezone.timedelta(seconds=45)
    huddle.participants.filter(last_ping__lt=cutoff).update(is_left=True)

    active_parts = huddle.participants.filter(is_left=False).select_related('user', 'user__profile')
    
    # If no active participants remain, close the huddle
    if not active_parts.exists():
        huddle.is_active = False
        huddle.ended_at = timezone.now()
        huddle.save()
        return JsonResponse({'is_active': False})

    participants_data = []
    current_in_huddle = False
    for p in active_parts:
        is_me = (p.user_id == request.user.id)
        if is_me:
            current_in_huddle = True
        participants_data.append({
            'user_id': p.user.id,
            'username': p.user.username,
            'name': p.user.get_full_name() or p.user.username,
            'initials': p.user.profile.initials if hasattr(p.user, 'profile') else p.user.username[:2].upper(),
            'avatar_color': p.user.profile.avatar_color if hasattr(p.user, 'profile') else '#1264A3',
            'is_muted': p.is_muted,
            'is_camera_on': p.is_camera_on,
            'is_screen_sharing': p.is_screen_sharing,
            'is_me': is_me,
        })

    duration_seconds = int((timezone.now() - huddle.started_at).total_seconds())

    return JsonResponse({
        'is_active': True,
        'huddle_id': huddle.id,
        'project_slug': project.slug,
        'project_name': project.name,
        'topic': huddle.topic or f"#{project.name} Huddle",
        'started_by': huddle.created_by.get_full_name() or huddle.created_by.username if huddle.created_by else 'Team member',
        'duration_seconds': duration_seconds,
        'participants_count': len(participants_data),
        'participants': participants_data,
        'current_in_huddle': current_in_huddle,
    })


@require_POST
@login_required(login_url='login')
def start_or_join_huddle(request, slug):
    """Starts a huddle if none exists, or joins the active huddle for the channel."""
    project = get_object_or_404(Project, slug=slug)
    topic = request.POST.get('topic', '').strip()

    huddle, created = Huddle.objects.get_or_create(
        project=project,
        is_active=True,
        defaults={
            'created_by': request.user,
            'topic': topic or f"#{project.name} Discussion",
        }
    )

    participant, _ = HuddleParticipant.objects.get_or_create(
        huddle=huddle,
        user=request.user,
        defaults={'is_left': False}
    )
    participant.is_left = False
    participant.last_ping = timezone.now()
    participant.save()

    return JsonResponse({
        'status': 'joined',
        'huddle_id': huddle.id,
        'created': created,
        'project_slug': project.slug,
        'project_name': project.name,
    })


@require_POST
@login_required(login_url='login')
def leave_huddle(request, slug):
    """Leaves the active huddle. If all participants leave, concludes the huddle."""
    project = get_object_or_404(Project, slug=slug)
    huddle = Huddle.objects.filter(project=project, is_active=True).first()

    if huddle:
        HuddleParticipant.objects.filter(huddle=huddle, user=request.user).update(is_left=True)
        # Check remaining
        remaining = huddle.participants.filter(is_left=False).count()
        if remaining == 0:
            huddle.is_active = False
            huddle.ended_at = timezone.now()
            huddle.save()

    return JsonResponse({'status': 'left'})


@require_POST
@login_required(login_url='login')
def update_huddle_state(request, slug):
    """Pings presence and toggles microphone/camera/screenshare states."""
    project = get_object_or_404(Project, slug=slug)
    huddle = Huddle.objects.filter(project=project, is_active=True).first()

    if not huddle:
        return JsonResponse({'error': 'No active huddle'}, status=404)

    participant = HuddleParticipant.objects.filter(huddle=huddle, user=request.user).first()
    if not participant:
        return JsonResponse({'error': 'Not in huddle'}, status=400)

    is_muted = request.POST.get('is_muted')
    is_camera_on = request.POST.get('is_camera_on')
    is_screen_sharing = request.POST.get('is_screen_sharing')

    if is_muted is not None:
        participant.is_muted = (is_muted.lower() in ['true', '1', 'yes'])
    if is_camera_on is not None:
        participant.is_camera_on = (is_camera_on.lower() in ['true', '1', 'yes'])
    if is_screen_sharing is not None:
        participant.is_screen_sharing = (is_screen_sharing.lower() in ['true', '1', 'yes'])

    participant.last_ping = timezone.now()
    participant.is_left = False
    participant.save()

    return JsonResponse({'status': 'ok'})


# ==============================================================================
# DIRECT MESSAGES VIEW
# ==============================================================================

@login_required(login_url='login')
def direct_message_view(request, username):
    """Direct 1-on-1 Slack conversation thread with another member or self"""
    target_user = get_object_or_404(User, username=username)
    current_user = request.user

    # Fetch all direct messages between current_user and target_user
    if current_user == target_user:
        dms_qs = DirectMessage.objects.filter(sender=current_user, recipient=current_user).order_by('created_at')
    else:
        dms_qs = DirectMessage.objects.filter(
            (models.Q(sender=current_user, recipient=target_user) |
             models.Q(sender=target_user, recipient=current_user))
        ).order_by('created_at')

    # Group messages by date
    dms_by_date = {}
    for dm in dms_qs:
        d_key = dm.created_at.date()
        if d_key not in dms_by_date:
            dms_by_date[d_key] = []
        dms_by_date[d_key].append(dm)

    return render(request, 'direct_messages.html', {
        'target_user': target_user,
        'current_user': current_user,
        'dms_by_date': dms_by_date,
        'dms_count': dms_qs.count(),
        'is_self_dm': (current_user == target_user),
    })


@require_POST
@login_required(login_url='login')
def send_direct_message(request, username):
    """Send a direct message to a user"""
    target_user = get_object_or_404(User, username=username)
    content = request.POST.get('content', '').strip()

    if content:
        dm = DirectMessage.objects.create(
            sender=request.user,
            recipient=target_user,
            content=content
        )
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({
                'status': 'ok',
                'id': dm.id,
                'sender': dm.sender.get_full_name() or dm.sender.username,
                'sender_username': dm.sender.username,
                'sender_initials': dm.sender.profile.initials if hasattr(dm.sender, 'profile') else dm.sender.username[:2].upper(),
                'sender_color': dm.sender.profile.avatar_color if hasattr(dm.sender, 'profile') else '#1264A3',
                'content': dm.content,
                'html': dm.formatted_content_html,
                'time': dm.created_at.strftime('%H:%M'),
            })

        messages.success(request, "Message sent.")

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'error': 'Message cannot be empty.'}, status=400)

    return redirect('direct_messages', username=username)


@require_POST
@login_required(login_url='login')
def edit_direct_message(request, message_id):
    """Edit a direct message"""
    dm = get_object_or_404(DirectMessage, id=message_id)
    if dm.sender != request.user and not request.user.is_staff:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        messages.error(request, 'Permission denied.')
        return redirect(request.META.get('HTTP_REFERER', '/'))

    content = request.POST.get('content', '').strip()
    if content:
        dm.content = content
        dm.save()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({
            'status': 'ok',
            'message_id': dm.id,
            'content': dm.content,
            'html': dm.formatted_content_html,
        })

    messages.success(request, 'Message updated.')
    return redirect(request.META.get('HTTP_REFERER', '/'))


@require_POST
@login_required(login_url='login')
def delete_direct_message(request, message_id):
    """Delete a direct message"""
    dm = get_object_or_404(DirectMessage, id=message_id)
    if dm.sender != request.user and not request.user.is_staff:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        messages.error(request, 'Permission denied.')
        return redirect(request.META.get('HTTP_REFERER', '/'))

    dm.delete()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'status': 'ok', 'message_id': message_id})

    messages.success(request, 'Message deleted.')
    return redirect(request.META.get('HTTP_REFERER', '/'))


@require_POST
@login_required(login_url='login')
def forward_message(request):
    """Forward a channel report or a direct message to a project channel or direct message recipient"""
    content = request.POST.get('content', '').strip()
    dest_type = request.POST.get('dest_type', 'channel') # 'channel' or 'dm'
    dest_id = request.POST.get('dest_id', '').strip()

    if not content:
        messages.error(request, 'No content to forward.')
        return redirect(request.META.get('HTTP_REFERER', '/'))

    forward_header = f"↳ Forwarded by @{request.user.username}:\n{content}"

    if dest_type == 'dm':
        target_user = get_object_or_404(User, username=dest_id)
        DirectMessage.objects.create(
            sender=request.user,
            recipient=target_user,
            content=forward_header
        )
        messages.success(request, f"Forwarded to @{target_user.username}!")
        return redirect('direct_messages', username=target_user.username)
    else:
        # Destination is channel project slug
        project = get_object_or_404(Project, slug=dest_id)
        report = DailyReport.objects.create(
            project=project,
            author=request.user,
            date=timezone.now().date(),
            content=forward_header
        )
        auto_tag_mentions(report, forward_header)
        messages.success(request, f"Forwarded to #{project.name}!")
        return redirect('project_detail', slug=project.slug)


# ==============================================================================
# REAL-TIME SLACK TYPING INDICATOR API
# ==============================================================================
from django.core.cache import cache
import time

@require_POST
@login_required(login_url='login')
def report_typing_status(request):
    """Client notifies server that request.user is currently typing in a channel or DM thread"""
    room_type = request.POST.get('room_type', 'channel') # 'channel' or 'dm'
    room_id = request.POST.get('room_id', '').strip()     # project slug or other username
    
    if not room_id:
        return JsonResponse({'status': 'ignored'})

    if room_type == 'dm':
        participants = sorted([request.user.username.lower(), room_id.lower()])
        cache_key = f"typing_dm_{participants[0]}_{participants[1]}"
    else:
        cache_key = f"typing_channel_{room_id.lower()}"

    typing_users = cache.get(cache_key, {})
    now = time.time()
    display_name = request.user.get_full_name() or request.user.username
    typing_users[request.user.username] = {
        'display_name': display_name,
        'username': request.user.username,
        'timestamp': now
    }
    cache.set(cache_key, typing_users, timeout=10)
    return JsonResponse({'status': 'ok'})


@login_required(login_url='login')
def get_typing_status(request):
    """Fetches list of active users typing in this room (excluding current user)"""
    room_type = request.GET.get('room_type', 'channel')
    room_id = request.GET.get('room_id', '').strip()

    if not room_id:
        return JsonResponse({'typing_users': []})

    if room_type == 'dm':
        participants = sorted([request.user.username.lower(), room_id.lower()])
        cache_key = f"typing_dm_{participants[0]}_{participants[1]}"
    else:
        cache_key = f"typing_channel_{room_id.lower()}"

    typing_users = cache.get(cache_key, {})
    now = time.time()
    active_typers = []
    updated_dict = {}

    for uname, data in typing_users.items():
        if now - data['timestamp'] < 4.0:
            updated_dict[uname] = data
            if uname != request.user.username:
                active_typers.append(data['display_name'])

    cache.set(cache_key, updated_dict, timeout=10)
    return JsonResponse({'typing_users': active_typers})


@login_required(login_url='login')
def fetch_latest_messages(request):
    """Fetches messages sent after last_id for 2-second live refresh without reloading page"""
    room_type = request.GET.get('room_type', 'channel')
    room_id = request.GET.get('room_id', '').strip()
    after_id = int(request.GET.get('after_id', 0))

    new_items = []

    if room_type == 'dm':
        target_user = get_object_or_404(User, username=room_id)
        current_user = request.user
        qs = DirectMessage.objects.filter(
            id__gt=after_id
        ).filter(
            (models.Q(sender=current_user, recipient=target_user) |
             models.Q(sender=target_user, recipient=current_user))
        ).select_related('sender', 'sender__profile').order_by('id')[:20]

        for m in qs:
            new_items.append({
                'id': m.id,
                'sender': m.sender.get_full_name() or m.sender.username,
                'sender_username': m.sender.username,
                'sender_initials': m.sender.profile.initials if hasattr(m.sender, 'profile') else m.sender.username[:2].upper(),
                'sender_color': m.sender.profile.avatar_color if hasattr(m.sender, 'profile') else '#1264A3',
                'html': m.formatted_content_html,
                'time': m.created_at.strftime('%H:%M'),
                'is_current_user': (m.sender == current_user)
            })
    else:
        project = get_object_or_404(Project, slug=room_id)
        qs = DailyReport.objects.filter(
            project=project,
            id__gt=after_id
        ).select_related('author', 'author__profile').order_by('id')[:20]

        for r in qs:
            new_items.append({
                'id': r.id,
                'author': r.author.get_full_name() or r.author.username,
                'author_username': r.author.username,
                'author_role': r.author.profile.role if hasattr(r.author, 'profile') else 'Member',
                'author_initials': r.author.profile.initials if hasattr(r.author, 'profile') else r.author.username[:2].upper(),
                'author_color': r.author.profile.avatar_color if hasattr(r.author, 'profile') else '#1264A3',
                'html': r.message_html,
                'time': r.created_at.strftime('%I:%M %p').lstrip('0'),
                'is_current_user': (r.author == request.user)
            })

    return JsonResponse({'messages': new_items})




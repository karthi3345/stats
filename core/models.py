import re
from collections import defaultdict
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.safestring import mark_safe


SLACK_COLORS = [
    '#4A154B', '#1264A3', '#2EB67D', '#ECB22E', 
    '#E01E5A', '#36C5F0', '#611f69', '#007a5a', '#1d1c1d'
]


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=100, default='Software Engineer')
    department = models.CharField(max_length=100, blank=True, default='Engineering')
    avatar_color = models.CharField(max_length=20, default='#1264A3')
    status_message = models.CharField(max_length=120, blank=True, default='Available')
    is_online = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.role})"

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def initials(self):
        full_name = self.user.get_full_name()
        if full_name:
            parts = full_name.strip().split()
            if len(parts) >= 2:
                return f"{parts[0][0]}{parts[-1][0]}".upper()
            return parts[0][:2].upper()
        return self.user.username[:2].upper()


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        color_idx = sum(ord(c) for c in instance.username) % len(SLACK_COLORS)
        UserProfile.objects.create(
            user=instance,
            avatar_color=SLACK_COLORS[color_idx]
        )
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()


class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    team_name = models.CharField(max_length=150, blank=True, default='')
    supervisor = models.CharField(max_length=150, blank=True, default='')
    confluence_page_title = models.CharField(max_length=200, blank=True, default='')
    color = models.CharField(max_length=20, default='#1264A3')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_projects')
    members = models.ManyToManyField(User, related_name='projects', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"#{self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def member_count(self):
        return self.members.count()


class DailyReport(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='reports')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_reports')
    date = models.DateField(default=timezone.now)
    priority = models.CharField(max_length=100, default='Medium', help_text="Priority e.g. Low, High, Perform sanity testing")
    links_notes = models.CharField(max_length=400, blank=True, default='', help_text="Links/notes(jira/confluence etc anything)")

    content = models.TextField(blank=True, default='', help_text="Chat message / daily status update")
    what_done_today = models.TextField(blank=True, default='', help_text="What I done today")
    issues_faced = models.TextField(blank=True, default='', help_text="What issue I faced")
    needed_from_others = models.TextField(blank=True, default='', help_text="Needed from other end")

    yesterday_work = models.TextField(blank=True, default='', help_text="What did you complete / work on yesterday?")
    today_plan = models.TextField(blank=True, default='', help_text="What are you focusing on today?")
    blockers = models.TextField(blank=True, default='', help_text="Any blockers / impediments?")
    tagged_users = models.ManyToManyField(User, related_name='tagged_in_reports', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'created_at']

    def __str__(self):
        return f"{self.author.username} - #{self.project.name} ({self.created_at.strftime('%H:%M')})"

    @property
    def has_blockers(self):
        return bool((self.blockers and self.blockers.strip() and self.blockers.strip().lower() not in ['none', 'no', 'nil', 'na', 'n/a']) or
                    (self.issues_faced and self.issues_faced.strip() and self.issues_faced.strip().lower() not in ['none', 'no', 'nil', 'na', 'n/a']))

    def format_text_with_mentions(self, text):
        """Replaces @username with styled Slack mention pills"""
        if not text:
            return ""
        def replace_mention(match):
            uname = match.group(1)
            try:
                u = User.objects.get(username__iexact=uname)
                full = u.get_full_name() or u.username
                return f'<a href="/feed/?member={uname}" class="slack-mention" title="{full} (@{uname})">@{uname}</a>'
            except User.DoesNotExist:
                return match.group(0)

        formatted = re.sub(r'@([a-zA-Z0-9_\.\-]+)', replace_mention, text)
        return mark_safe(formatted)

    @property
    def what_done_today_html(self):
        return self.format_text_with_mentions(self.what_done_today)

    @property
    def issues_faced_html(self):
        return self.format_text_with_mentions(self.issues_faced)

    @property
    def needed_from_others_html(self):
        return self.format_text_with_mentions(self.needed_from_others)

    @property
    def yesterday_work_html(self):
        return self.format_text_with_mentions(self.yesterday_work)

    @property
    def today_plan_html(self):
        return self.format_text_with_mentions(self.today_plan)

    @property
    def blockers_html(self):
        return self.format_text_with_mentions(self.blockers)

    @property
    def message_html(self):
        # 1. Confluence-style Status Document Card
        if self.what_done_today or self.issues_faced or self.needed_from_others:
            issues_snippet = ""
            if self.issues_faced and self.issues_faced.strip().lower() not in ['none', 'no', 'nil', 'na', 'n/a']:
                issues_snippet = f'''
                <div class="confluence-section" style="margin-top:8px;">
                  <div class="field-header-tag tag-blocker" style="margin-bottom:3px;">
                    <span>⚠️</span> <strong>What Issue I Faced:</strong>
                  </div>
                  <div class="field-content-text blocker-alert-box">{self.issues_faced_html}</div>
                </div>'''
            else:
                issues_snippet = '''
                <div class="confluence-section" style="margin-top:8px;">
                  <div class="field-header-tag tag-blocker" style="margin-bottom:3px;">
                    <span>🟢</span> <strong>What Issue I Faced:</strong>
                  </div>
                  <div class="field-content-text" style="color:#777; font-style:italic;">No issues faced &bull; All clear</div>
                </div>'''

            needed_snippet = ""
            if self.needed_from_others and self.needed_from_others.strip().lower() not in ['none', 'no', 'nil', 'na', 'n/a']:
                needed_snippet = f'''
                <div class="confluence-section" style="margin-top:8px;">
                  <div class="field-header-tag tag-doing" style="margin-bottom:3px; color:#1264A3;">
                    <span>🤝</span> <strong>Needed From Other End:</strong>
                  </div>
                  <div class="field-content-text" style="background:#F0F7FA; border:1px solid #D5EBF5; padding:8px 12px; border-radius:6px; color:#1264A3; font-weight:600;">
                    {self.needed_from_others_html}
                  </div>
                </div>'''
            else:
                needed_snippet = '''
                <div class="confluence-section" style="margin-top:8px;">
                  <div class="field-header-tag tag-doing" style="margin-bottom:3px; color:#1264A3;">
                    <span>🤝</span> <strong>Needed From Other End:</strong>
                  </div>
                  <div class="field-content-text" style="color:#777; font-style:italic;">No dependencies from others</div>
                </div>'''

            card = f'''
            <div class="confluence-doc-card" style="border-left: 4px solid #0052CC; background: #FAFBFC; border: 1px solid #DFE1E6; border-left-width: 4px; border-radius: 6px; padding: 14px 16px; margin-top: 6px; box-shadow: 0 1px 3px rgba(9, 30, 66, 0.08);">
              <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; border-bottom:1px solid #EBECF0; padding-bottom:6px;">
                <span style="font-size:12px; font-weight:800; color:#0052CC; display:flex; align-items:center; gap:5px;">
                  <span>📄</span> CONFLUENCE DAILY STATUS REPORT
                </span>
                <span style="font-size:11.5px; font-weight:700; color:#6B778C;">📅 {self.date.strftime('%B %d, %Y')}</span>
              </div>

              <!-- 1. What I Done Today -->
              <div class="confluence-section">
                <div class="field-header-tag tag-done" style="margin-bottom:3px; color:#007A5A;">
                  <span>✅</span> <strong>What I Done Today:</strong>
                </div>
                <div class="field-content-text" style="background:#FFF; border:1px solid #EBECF0; padding:8px 12px; border-radius:6px; line-height:1.5;">
                  {self.what_done_today_html or 'None'}
                </div>
              </div>

              <!-- 2. What Issue I Faced -->
              {issues_snippet}

              <!-- 3. Needed From Other End -->
              {needed_snippet}
            </div>'''
            return mark_safe(card)

        # 2. Legacy Standup Card
        if self.yesterday_work or self.today_plan:
            card = f'''
            <div class="slack-attachment-card" style="margin-top:4px;">
              <div class="attachment-field-row">
                <span class="field-header-tag tag-done"><span>✅</span> Yesterday's Progress:</span>
                <div class="field-content-text">{self.yesterday_work_html or 'None'}</div>
              </div>
              <div class="attachment-field-row" style="margin-top:6px;">
                <span class="field-header-tag tag-doing"><span>🎯</span> Today's Focus:</span>
                <div class="field-content-text">{self.today_plan_html or 'None'}</div>
              </div>
            </div>'''
            return mark_safe(card)

        # 3. Quick Chat Message
        return self.format_text_with_mentions(self.content)

    def get_reaction_summary(self, current_user=None):
        """Returns actual manual reactions grouped by emoji"""
        grouped = defaultdict(lambda: {'emoji': '', 'count': 0, 'users': [], 'user_reacted': False})
        for r in self.reactions.all().select_related('user'):
            g = grouped[r.emoji]
            g['emoji'] = r.emoji
            g['count'] += 1
            g['users'].append(r.user.get_full_name() or r.user.username)
            if current_user and current_user.is_authenticated and r.user_id == current_user.id:
                g['user_reacted'] = True
        return list(grouped.values())


class ReportReaction(models.Model):
    report = models.ForeignKey(DailyReport, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reactions')
    emoji = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('report', 'user', 'emoji')

    def __str__(self):
        return f"{self.user.username} {self.emoji} on #{self.report_id}"


class ReportComment(models.Model):
    report = models.ForeignKey(DailyReport, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='report_comments')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.username} on Report #{self.report_id}"



class ProjectTask(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    status = models.CharField(max_length=60, default='todo')
    priority = models.CharField(max_length=20, choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('urgent', 'Urgent'), ('critical', 'Critical')], default='medium')
    assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='assigned_tasks')
    reporter = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='reported_tasks')
    due_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    story_points = models.PositiveIntegerField(default=1, null=True, blank=True)
    labels = models.CharField(max_length=200, blank=True, default='') # comma-separated e.g. "Frontend, Security"
    epic_name = models.CharField(max_length=100, blank=True, default='')
    sprint_name = models.CharField(max_length=100, blank=True, default='Sprint 1')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_tasks')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # New field for Jira-like issue type
    ISSUE_TYPE_CHOICES = [
        ('story', 'Story'),
        ('bug', 'Bug'),
        ('task', 'Task'),
        ('epic', 'Epic'),
    ]
    issue_type = models.CharField(max_length=10, choices=ISSUE_TYPE_CHOICES, default='task')
    
    @property
    def labels_list(self):
        if not self.labels:
            return []
        # Support comma, semicolon, space separated labels
        raw = [l.strip() for l in re.split(r'[,;]+', self.labels) if l.strip()]
        return raw

    def __str__(self):
        return f"{self.title} ({self.status})"

class TaskComment(models.Model):
    task = models.ForeignKey('ProjectTask', on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='task_comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment by {self.author} on {self.task}" 


class TaskSubtask(models.Model):
    task = models.ForeignKey('ProjectTask', on_delete=models.CASCADE, related_name='subtasks')
    title = models.CharField(max_length=255)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.title} ({'done' if self.is_completed else 'pending'})"


class TaskAttachment(models.Model):
    task = models.ForeignKey('ProjectTask', on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='task_attachments/', blank=True, null=True)
    filename = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.filename} on {self.task}"
 

class KanbanColumn(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='kanban_columns')
    name = models.CharField(max_length=60) # Display title e.g. "To Do", "QA Testing", "Deployed"
    slug = models.SlugField(max_length=60) # Key used in task.status e.g. "todo", "qa-testing"
    order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=20, default='#0052CC') # Accent color hex
    wip_limit = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']
        unique_together = ('project', 'slug')

    def __str__(self):
        return f"{self.project.name} - {self.name} ({self.slug})"


class Huddle(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='huddles')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='started_huddles')
    is_active = models.BooleanField(default=True)
    topic = models.CharField(max_length=200, blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        status = "Active" if self.is_active else "Ended"
        return f"Huddle in #{self.project.name} ({status})"


class HuddleParticipant(models.Model):
    huddle = models.ForeignKey(Huddle, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='huddle_participations')
    joined_at = models.DateTimeField(auto_now_add=True)
    last_ping = models.DateTimeField(auto_now=True)
    is_muted = models.BooleanField(default=False)
    is_camera_on = models.BooleanField(default=False)
    is_screen_sharing = models.BooleanField(default=False)
    is_left = models.BooleanField(default=False)

    class Meta:
        unique_together = ('huddle', 'user')

    def __str__(self):
        return f"{self.user.username} in Huddle #{self.huddle_id}"


class ProjectConfluenceSection(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='confluence_sections')
    date = models.DateField()
    custom_title = models.CharField(max_length=150, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        unique_together = ('project', 'date')

    def __str__(self):
        return f"{self.project.name} - {self.date}"

    @property
    def display_title(self):
        if self.custom_title:
            return self.custom_title
        return f"{self.date.strftime('%A')} <{self.date.strftime('%d-%m-%Y')}>"

    @property
    def anchor(self):
        return f"day-{self.date.strftime('%Y%m%d')}"


class DirectMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_direct_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_direct_messages')
    content = models.TextField(help_text="Direct message text content")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"DM from {self.sender.username} to {self.recipient.username} at {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def formatted_content_html(self):
        """Formats URLs, file references, code snippets, and link preview cards like Slack"""
        text = self.content or ""
        import html
        escaped = html.escape(text)

        # Detect URLs
        url_pattern = re.compile(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)')
        urls = url_pattern.findall(escaped)

        # Format URLs as clickable links
        def replace_url(match):
            u = match.group(0)
            href = u if u.startswith('http') else 'https://' + u
            return f'<a href="{href}" target="_blank" rel="noopener noreferrer" class="slack-link-preview-anchor">{u}</a>'

        formatted = url_pattern.sub(replace_url, escaped)

        # Generate link preview cards if URLs are present
        preview_cards = []
        for raw_url in urls[:2]:
            display_url = raw_url if raw_url.startswith('http') else 'https://' + raw_url
            domain = display_url.split('/')[2] if len(display_url.split('/')) > 2 else display_url

            # Extract clean title/summary based on domain or path
            clean_title = domain
            clean_desc = f"Preview for {display_url}"
            if "betbuilder" in display_url.lower() or "gambling" in display_url.lower():
                clean_title = "BetBuilderAI | Build smarter bets."
                clean_desc = "AI football predictions and bet builder tips for every match. Best odds, player props like anytime goalscorer, shots on target, tackles and cards."
            elif "viralmaxxing" in display_url.lower() or "job" in display_url.lower():
                clean_title = "Automation & Workflow Webhook Integration"
                clean_desc = "Turn keyword comments into DMs through official API. Understands Tamil, Tanglish, Hinglish, and English. Template rotation, follow-gates, tracked links."
            else:
                clean_title = f"{domain} | Resource"
                clean_desc = f"Direct link to {display_url} - Shared in direct conversation."

            preview_cards.append(f'''
            <div class="slack-unfurl-card">
              <div class="slack-unfurl-info">
                <div class="slack-unfurl-title"><a href="{display_url}" target="_blank">{clean_title}</a></div>
                <div class="slack-unfurl-description">{clean_desc}</div>
                <div class="slack-unfurl-domain">{domain}</div>
              </div>
              <div class="slack-unfurl-media">
                <div class="slack-unfurl-icon">🖼️</div>
              </div>
            </div>
            ''')

        # Detect file attachments or code like index.html or login.html
        file_matches = re.findall(r'\b([a-zA-Z0-9_\-]+\.(?:html|py|js|css|json|pdf|png|jpg))\b', escaped)
        file_cards = []
        for fn in set(file_matches[:2]):
            file_cards.append(f'''
            <div class="slack-file-snippet-card">
              <div class="slack-file-snippet-header">
                <span class="slack-file-badge">&lt;/&gt;</span>
                <div class="slack-file-meta">
                  <span class="slack-file-name">{fn}</span>
                  <span class="slack-file-action">View in Slack</span>
                </div>
                <div class="slack-file-actions-icons">
                  <button type="button" class="slack-mini-btn" title="Download">☁️</button>
                  <button type="button" class="slack-mini-btn" title="Edit">✏️</button>
                  <button type="button" class="slack-mini-btn" title="Share">🔗</button>
                  <button type="button" class="slack-mini-btn" title="More">⋯</button>
                </div>
              </div>
            </div>
            ''')

        extra_html = "".join(file_cards) + "".join(preview_cards)
        return mark_safe(f'<div class="dm-text-body">{formatted}</div>' + extra_html)





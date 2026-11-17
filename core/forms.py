from django import forms
from django.contrib.auth.models import User
from .models import Project, DailyReport, ReportComment

class ProjectForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'slack-select-multiple'})
    )

    class Meta:
        model = Project
        fields = ['name', 'description', 'color', 'members']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'slack-input', 'placeholder': 'e.g. mobile-app, client-portal, payments'}),
            'description': forms.Textarea(attrs={'class': 'slack-textarea', 'rows': 3, 'placeholder': 'What is this project about?'}),
            'color': forms.TextInput(attrs={'type': 'color', 'class': 'slack-color-picker', 'value': '#1264A3'}),
        }


class DailyReportForm(forms.ModelForm):
    tagged_users = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'slack-tag-select'})
    )

    class Meta:
        model = DailyReport
        fields = ['date', 'yesterday_work', 'today_plan', 'blockers', 'tagged_users']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'slack-input'}),
            'yesterday_work': forms.Textarea(attrs={
                'class': 'slack-textarea mention-input',
                'rows': 3,
                'placeholder': '• Shipped user authentication\n• Fixed invoice PDF alignment\nType @ to tag team members...'
            }),
            'today_plan': forms.Textarea(attrs={
                'class': 'slack-textarea mention-input',
                'rows': 3,
                'placeholder': '• Integrating Stripe webhooks with @karthik\n• Code review on pull request #42...'
            }),
            'blockers': forms.Textarea(attrs={
                'class': 'slack-textarea mention-input',
                'rows': 2,
                'placeholder': 'Waiting on API keys from DevOps, or enter None if unblocked...'
            }),
        }


class AddMembersForm(forms.Form):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'member-checkbox'})
    )

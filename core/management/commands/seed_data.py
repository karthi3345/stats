from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import UserProfile, Project, DailyReport, ReportComment
from core.views import auto_tag_mentions


class Command(BaseCommand):
    help = 'Seeds sample users, projects, and daily status reports'

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding Slack DSR demo data...")

        # 1. Create Users
        users_data = [
            {
                'username': 'karthik',
                'first_name': 'Karthik',
                'last_name': 'Raja',
                'email': 'karthik@company.com',
                'role': 'Lead Architect & Full Stack',
                'color': '#4A154B',
                'status': '🚀 Shipping new features',
            },
            {
                'username': 'sarah',
                'first_name': 'Sarah',
                'last_name': 'Chen',
                'email': 'sarah@company.com',
                'role': 'Senior Frontend Engineer',
                'color': '#1264A3',
                'status': '🎨 Refining UI & component library',
            },
            {
                'username': 'alex',
                'first_name': 'Alex',
                'last_name': 'Rivera',
                'email': 'alex@company.com',
                'role': 'Backend & API Specialist',
                'color': '#2EB67D',
                'status': '⚙️ Optimizing database queries',
            },
            {
                'username': 'priya',
                'first_name': 'Priya',
                'last_name': 'Sharma',
                'email': 'priya@company.com',
                'role': 'Product Manager',
                'color': '#E01E5A',
                'status': '🗓️ Sprint planning & roadmap',
            },
            {
                'username': 'marcus',
                'first_name': 'Marcus',
                'last_name': 'Vance',
                'email': 'marcus@company.com',
                'role': 'DevOps & Cloud Engineer',
                'color': '#ECB22E',
                'status': '☁️ Kubernetes & CI/CD pipelines',
            },
            {
                'username': 'emily',
                'first_name': 'Emily',
                'last_name': 'Watson',
                'email': 'emily@company.com',
                'role': 'QA Automation Lead',
                'color': '#36C5F0',
                'status': '🔍 Writing E2E test suites',
            },
        ]

        user_objs = {}
        for udata in users_data:
            user, created = User.objects.get_or_create(
                username=udata['username'],
                defaults={
                    'first_name': udata['first_name'],
                    'last_name': udata['last_name'],
                    'email': udata['email'],
                }
            )
            if created:
                user.set_password('password123')
                user.save()

            # Profile
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = udata['role']
            profile.avatar_color = udata['color']
            profile.status_message = udata['status']
            profile.save()

            user_objs[udata['username']] = user

        # 2. Create Projects
        projects_data = [
            {
                'name': 'mobile-banking-app',
                'description': 'Next-gen iOS and Android digital banking application with biometric login and instant transfers.',
                'color': '#4A154B',
                'creator': user_objs['karthik'],
                'members': [user_objs['karthik'], user_objs['sarah'], user_objs['alex'], user_objs['priya']],
            },
            {
                'name': 'ecommerce-platform',
                'description': 'High-throughput storefront, cart service, and multi-currency Stripe payment gateway integration.',
                'color': '#1264A3',
                'creator': user_objs['priya'],
                'members': [user_objs['karthik'], user_objs['alex'], user_objs['emily']],
            },
            {
                'name': 'ai-analytics-dashboard',
                'description': 'Real-time telemetry, user behavior clustering, and LLM-powered business intelligence reports.',
                'color': '#2EB67D',
                'creator': user_objs['alex'],
                'members': [user_objs['sarah'], user_objs['alex'], user_objs['karthik']],
            },
            {
                'name': 'cloud-infra-devops',
                'description': 'AWS EKS cluster setup, zero-downtime CI/CD workflows, Terraform scripts, and Datadog monitoring.',
                'color': '#ECB22E',
                'creator': user_objs['marcus'],
                'members': [user_objs['marcus'], user_objs['karthik'], user_objs['emily']],
            },
        ]

        proj_objs = {}
        for pdata in projects_data:
            proj, _ = Project.objects.get_or_create(
                name=pdata['name'],
                defaults={
                    'description': pdata['description'],
                    'color': pdata['color'],
                    'created_by': pdata['creator'],
                }
            )
            proj.members.set(pdata['members'])
            proj_objs[pdata['name']] = proj

        # 3. Create Daily Reports for Today and Yesterday with realistic @mentions
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        reports_data = [
            # Mobile Banking - Today
            {
                'project': proj_objs['mobile-banking-app'],
                'author': user_objs['karthik'],
                'date': today,
                'yesterday_work': '• Designed the transaction flow architecture\n• Reviewed the authentication pull request from @alex\n• Set up JWT refresh tokens endpoint',
                'today_plan': '• Pairing with @sarah on the biometrics biometric PIN screen\n• Finalizing end-to-end integration tests\n• Preparing release notes for @priya',
                'blockers': 'None. Ready to deploy staging build by 4 PM.',
                'tagged': [user_objs['sarah'], user_objs['alex'], user_objs['priya']],
            },
            {
                'project': proj_objs['mobile-banking-app'],
                'author': user_objs['sarah'],
                'date': today,
                'yesterday_work': '• Built responsive bottom sheet navigation modal\n• Connected account balance widget to GraphQL API',
                'today_plan': '• Working on biometric prompt screens with @karthik\n• Resolving dark mode contrast glitches on iOS',
                'blockers': 'Waiting on updated Figma tokens from UI team.',
                'tagged': [user_objs['karthik']],
            },
            {
                'project': proj_objs['mobile-banking-app'],
                'author': user_objs['alex'],
                'date': today,
                'yesterday_work': '• Implemented rate-limiting middleware for auth routes\n• Reduced database latency on balance query by 40%',
                'today_plan': '• Assisting @karthik with transaction state machines\n• Reviewing PostgreSQL connection pool configurations with @marcus',
                'blockers': 'Need staging RDS read replica access from @marcus.',
                'tagged': [user_objs['karthik'], user_objs['marcus']],
            },
            # Mobile Banking - Yesterday
            {
                'project': proj_objs['mobile-banking-app'],
                'author': user_objs['priya'],
                'date': yesterday,
                'yesterday_work': '• Conducted usability session with beta users\n• Documented feedback on transfer confirmation dialog',
                'today_plan': '• Prioritizing sprint backlog for v2 release\n• Reviewing blocker with @sarah and @karthik',
                'blockers': 'None.',
                'tagged': [user_objs['sarah'], user_objs['karthik']],
            },
            # E-Commerce Platform - Today
            {
                'project': proj_objs['ecommerce-platform'],
                'author': user_objs['alex'],
                'date': today,
                'yesterday_work': '• Added Stripe webhook idempotency keys\n• Fixed race condition in cart checkout session',
                'today_plan': '• Stress testing payment capture under high concurrency\n• Helping @emily write automated refund test cases',
                'blockers': 'None.',
                'tagged': [user_objs['emily']],
            },
            {
                'project': proj_objs['ecommerce-platform'],
                'author': user_objs['emily'],
                'date': today,
                'yesterday_work': '• Wrote 15 Playwright E2E tests for guest checkout\n• Logged 2 edge-case defects in promo code validation',
                'today_plan': '• Collaborating with @alex on testing webhook failure retries\n• Performance benchmarking order processing',
                'blockers': 'Staging mock payment service was intermittently timing out.',
                'tagged': [user_objs['alex']],
            },
            # Cloud DevOps - Today
            {
                'project': proj_objs['cloud-infra-devops'],
                'author': user_objs['marcus'],
                'date': today,
                'yesterday_work': '• Upgraded Kubernetes cluster to v1.30\n• Provisioned Redis caching cluster via Terraform',
                'today_plan': '• Granting RDS read-replica permissions for @alex\n• Setting up GitHub Actions caching for @karthik and team',
                'blockers': 'None.',
                'tagged': [user_objs['alex'], user_objs['karthik']],
            },
        ]

        for rdata in reports_data:
            report, _ = DailyReport.objects.get_or_create(
                project=rdata['project'],
                author=rdata['author'],
                date=rdata['date'],
                defaults={
                    'yesterday_work': rdata['yesterday_work'],
                    'today_plan': rdata['today_plan'],
                    'blockers': rdata['blockers'],
                }
            )
            report.tagged_users.set(rdata['tagged'])
            # Auto parse mentions in text too
            auto_tag_mentions(report, f"{rdata['yesterday_work']} {rdata['today_plan']} {rdata['blockers']}")

        # 4. Add a sample comment
        sample_rep = DailyReport.objects.filter(project=proj_objs['mobile-banking-app'], author=user_objs['alex']).first()
        if sample_rep:
            ReportComment.objects.get_or_create(
                report=sample_rep,
                author=user_objs['marcus'],
                defaults={
                    'message': '@alex Just provisioned the RDS read replica access for your staging IAM role! You can connect now.'
                }
            )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully!"))
        self.stdout.write(f"Created {len(users_data)} users, {len(projects_data)} projects, and {len(reports_data)} daily reports.")

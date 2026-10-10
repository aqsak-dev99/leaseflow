"""Creating and reading notifications.

Other apps call `notify` or `notify_landlords` at the moment something happens
(a ticket is opened, a payment arrives, a waiver is decided). A notification
always belongs to one user, and every read goes through `for_user`, so nobody
can see or open another person's notifications.
"""

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.accounts.models import User

from .models import Notification


def notify(*, user, kind, title, body="", url=""):
    """Tell one user about something. Returns the notification."""
    return Notification.objects.create(
        organization=user.organization,
        user=user,
        kind=kind,
        title=title[:200],
        body=body[:300],
        url=url[:200],
    )


def notify_landlords(organization, **details):
    """Tell every landlord in an organization. Returns the notifications created."""
    landlords = User.objects.filter(organization=organization, role=User.Role.LANDLORD)
    return [notify(user=landlord, **details) for landlord in landlords]


def for_user(user):
    """This user's own notifications, newest first."""
    return Notification.objects.for_org(user.organization).filter(user=user)


def unread_count(user):
    return for_user(user).filter(read_at__isnull=True).count()


def mark_all_read(user):
    return for_user(user).filter(read_at__isnull=True).update(read_at=timezone.now())


def open_notification(user, notification_id):
    """Mark one of the user's notifications as read and return where it points."""
    notification = for_user(user).filter(pk=notification_id).first()
    if notification is None:
        raise PermissionDenied("Notification not found.")
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return notification.url


def display_name(user):
    return user.get_full_name() or user.email

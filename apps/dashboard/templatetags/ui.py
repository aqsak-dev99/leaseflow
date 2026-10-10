"""Small template helpers for the interface: icons, initials and navigation state."""

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.timesince import timesince

register = template.Library()

ICONS = {
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/>',
    "building": '<path d="M4 21V5l8-2v18"/><path d="M12 9l8 2v10"/><path d="M2 21h20"/>',
    "wrench": '<path d="M14.5 6.5a4 4 0 0 0 5 5L11 20a2.1 2.1 0 0 1-3-3z"/>'
    '<path d="M14.5 6.5l3-3"/>',
    "card": '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9"/><path d="M16 7l3 3"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5v.5"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/>',
    "doc": '<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h5"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4'
    'M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/>',
    "send": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "back": '<path d="M15 5l-7 7 7 7"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
    '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.2a6.5 6.5 0 0 1 3.5 5.8"/>',
    "bell": '<path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "arrow": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/>'
    '<circle cx="12" cy="12" r="3"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6z"/>'
    '<path d="M9 12l2 2 4-4"/>',
}

NOTIFICATION_ICONS = {"rent": "card", "repair": "wrench", "approval": "doc", "tenant": "users"}

ASSISTANTS = {
    "lease": "Lease assistant",
    "maintenance": "Repairs assistant",
    "payment": "Payments assistant",
}


@register.simple_tag
def icon(name, size=20):
    """An inline line icon that takes the colour of the text around it."""
    return format_html(
        '<svg class="icon icon-{}" width="{}" height="{}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">{}</svg>',
        name,
        size,
        size,
        mark_safe(ICONS[name]),
    )


@register.filter
def initials(user):
    """Two letters for the avatar: from the name if there is one, otherwise the email."""
    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "last_name", "") or "").strip()
    if first and last:
        return (first[0] + last[0]).upper()
    source = first or (getattr(user, "email", "") or "?")
    return source[:2].upper()


@register.simple_tag(takes_context=True)
def current(context, names):
    """Mark a navigation link as the current page when the URL name is one of `names`."""
    match = getattr(context.get("request"), "resolver_match", None)
    if match is not None and match.url_name in names.split(","):
        return mark_safe(' aria-current="page"')
    return ""


@register.filter
def assistant_name(message):
    """Which assistant wrote a chat reply, from the route its run took."""
    run = getattr(message, "run", None)
    return ASSISTANTS.get(getattr(run, "route", ""), "Assistant")


@register.filter
def verified(message):
    """True when the verifier checked this reply against the lease and supported it."""
    run = getattr(message, "run", None)
    for step in getattr(run, "steps", None) or []:
        if step.get("name") == "verifier":
            return (step.get("detail") or {}).get("verdict") == "supported"
    return False


@register.simple_tag
def notification_icon(notification, size=18):
    """The icon for a notification, chosen by what it is about."""
    return icon(NOTIFICATION_ICONS.get(notification.kind, "bell"), size)


@register.filter
def ago(moment):
    """A short "how long ago" for lists: "Just now", "5 minutes ago", "2 days ago"."""
    if (timezone.now() - moment).total_seconds() < 60:
        return "Just now"
    return timesince(moment, depth=1) + " ago"


@register.filter
def with_placeholder(field):
    """Render a form field with its label shown inside the box as a placeholder."""
    return field.as_widget(attrs={"placeholder": field.label})

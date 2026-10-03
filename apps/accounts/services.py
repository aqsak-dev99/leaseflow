from django.db import transaction
from django.utils.text import slugify

from .models import Organization, User


def unique_slug(name):
    base = slugify(name) or "org"
    slug, number = base, 2
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{number}"
        number += 1
    return slug


@transaction.atomic
def signup_landlord(*, organization_name, email, password):
    """Create an organization and its first landlord together, or neither."""
    organization = Organization.objects.create(
        name=organization_name, slug=unique_slug(organization_name)
    )
    return User.objects.create_user(
        email=email,
        password=password,
        organization=organization,
        role=User.Role.LANDLORD,
    )

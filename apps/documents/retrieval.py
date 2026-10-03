from django.db.models import Q
from pgvector.django import CosineDistance

from apps.core.ai import embed_query

from .models import DocumentChunk


def search_chunks(*, organization, lease, query, limit=5):
    """Find the chunks closest in meaning to the query.

    The organization and lease filters run first, so a tenant can only ever get
    chunks from their own lease and their own organization's policy documents.
    """
    vector = embed_query(query)
    return list(
        DocumentChunk.objects.for_org(organization)
        .filter(Q(lease=lease) | Q(lease__isnull=True))
        .annotate(distance=CosineDistance("embedding", vector))
        .select_related("document")
        .order_by("distance")[:limit]
    )

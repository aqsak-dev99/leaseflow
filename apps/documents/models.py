from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.core.ai import EMBEDDING_DIMENSIONS
from apps.core.models import OrgScopedModel


class Document(OrgScopedModel):
    class Kind(models.TextChoices):
        LEASE = "lease", "Lease"
        POLICY = "policy", "Policy"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    lease = models.ForeignKey(
        "properties.Lease",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="documents/")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)

    def __str__(self):
        return self.title


class DocumentChunk(OrgScopedModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    lease = models.ForeignKey(
        "properties.Lease",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    page_number = models.PositiveIntegerField()
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)

    class Meta:
        indexes = [
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]

    def __str__(self):
        return f"{self.document.title} p{self.page_number} #{self.chunk_index}"

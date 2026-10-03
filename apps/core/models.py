from django.db import models


class OrgScopedQuerySet(models.QuerySet):
    def for_org(self, organization):
        return self.filter(organization=organization)


class OrgScopedModel(models.Model):
    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgScopedQuerySet.as_manager()

    class Meta:
        abstract = True

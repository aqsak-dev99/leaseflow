from django import forms

from apps.maintenance.models import MaintenanceTicket


class TicketStatusForm(forms.Form):
    status = forms.ChoiceField(choices=MaintenanceTicket.Status.choices)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    cost = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2)

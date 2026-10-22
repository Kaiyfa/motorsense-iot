"""Forms for the Maintenance tab (validated server-side; CSRF via Django's middleware)."""
from datetime import timedelta

from django import forms
from django.utils import timezone

from dashboard.models import MaintenanceEntry

FUTURE_TOLERANCE = timedelta(minutes=5)


class MaintenanceEntryForm(forms.ModelForm):
    performed_at = forms.DateTimeField(
        label='Performed at',
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )

    class Meta:
        model = MaintenanceEntry
        fields = ['performed_at', 'kind', 'notes']
        labels = {'kind': 'Kind', 'notes': 'Notes'}
        widgets = {'notes': forms.Textarea(attrs={'rows': 3, 'maxlength': 2000})}

    def clean_performed_at(self):
        value = self.cleaned_data['performed_at']
        if value > timezone.now() + FUTURE_TOLERANCE:
            raise forms.ValidationError('cannot be in the future.')
        return value

    def clean_notes(self):
        notes = self.cleaned_data.get('notes', '').strip()
        if len(notes) > 2000:
            raise forms.ValidationError('at most 2000 characters.')
        return notes


class InspectionIntervalForm(forms.Form):
    days = forms.IntegerField(label='Inspection interval (days)', min_value=1, max_value=3650)

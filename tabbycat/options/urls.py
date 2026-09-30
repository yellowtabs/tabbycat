from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path('global/', RedirectView.as_view(url='../', query_string=True), name='options-global-legacy-redirect'),
    # Overview
    path('',
        views.TournamentConfigIndexView.as_view(),
        name='options-tournament-index'),

    # Presets
    path('presets/<slug:preset_name>/confirm/',
        views.SetPresetPreferencesView.as_view(),
        name="options-presets-confirm"),

    # Per Type
    path('<slug:section>/',
        views.TournamentPreferenceFormView.as_view(),
        name="options-tournament-section"),
]

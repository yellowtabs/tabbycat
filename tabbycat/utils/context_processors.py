from urllib.parse import urlencode

from django.conf import settings

from tournaments.models import Tournament


def _yellowtabs_checkout_url():
    """Checkout URL for buying another edition, pre-scoped to this org."""
    base = getattr(settings, 'YELLOWTABS_CHECKOUT_URL', '')
    if not base:
        return ''
    org = getattr(settings, 'YELLOWTABS_ORG_SLUG', '')
    return f"{base}?{urlencode({'org': org})}" if org else base


def debate_context(request):

    context = {
        'tabbycat_version': settings.TABBYCAT_VERSION or "",
        'tabbycat_codename': settings.TABBYCAT_CODENAME or "no codename",
        'all_tournaments': Tournament.objects.filter(active=True),
        'disable_sentry': getattr(settings, 'DISABLE_SENTRY', False),
        'on_local': getattr(settings, 'ON_LOCAL', False),
        'hmr': getattr(settings, 'USE_WEBPACK_SERVER', False),
        # YellowTabs managed hosting: paywall the create-tournament action.
        'on_yellowtabs': getattr(settings, 'ON_YELLOWTABS', False),
        'yellowtabs_checkout_url': _yellowtabs_checkout_url(),
    }

    if hasattr(request, 'tournament'):
        current_round = request.tournament.current_round

        context.update({
            'tournament': request.tournament,
            'pref': request.tournament.preferences.by_name(),
            'current_round': current_round,
        })
        if hasattr(request, 'round'):
            context['round'] = request.round

    return context

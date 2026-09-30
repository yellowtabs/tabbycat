"""Extension points for tournament lifecycle events."""

from django.dispatch import Signal


first_draw_generated = Signal()
round_completed = Signal()

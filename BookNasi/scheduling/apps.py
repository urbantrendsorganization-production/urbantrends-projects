from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    name = "scheduling"

    def ready(self):
        # The availability cache listens to `shops` writes rather than `shops`
        # calling into it, which is what keeps the dependency running
        # scheduling -> shops and never back. See scheduling/invalidation.py.
        from scheduling import invalidation

        invalidation.connect()

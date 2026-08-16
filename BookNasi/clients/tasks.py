"""The retention sweep. CLAUDE.md §9.

A stated retention period that nothing executes is a sentence in a privacy
notice, and the DPA asks what a controller *does*. This is the doing.

One sweep, no per-client `eta` task — unlike hold release (slice 5) and
reminders (slice 8), which both pair a scheduled task with a sweep because
being late by minutes matters. Nothing here is time-critical to the minute: the
boundary is two years wide, and a record scrubbed on Tuesday rather than Monday
is not a different compliance posture. Arming a task two years out would also
be exactly what slice 8 refused — a promise held in a worker's memory across
every restart between now and then.
"""

import logging

from celery import shared_task

from clients import erasure
from clients.models import ScrubReason

logger = logging.getLogger(__name__)

#: A ceiling per run. A first sweep on a deployment that has been collecting for
#: two years could match thousands of rows, and each one is several writes
#: across four tables; taking them in daily bites keeps a routine job from
#: becoming a long transaction against the appointments table at whatever hour
#: Beat happens to fire. The remainder is picked up tomorrow, which for a
#: two-year boundary is not a delay anybody can be harmed by.
BATCH = 500


@shared_task(name="clients.scrub_expired_clients")
def scrub_expired_clients():
    """Scrub everyone past the retention period. Returns how many."""
    done = 0
    for client in erasure.expired_clients()[:BATCH]:
        erasure.erase(client, reason=ScrubReason.RETENTION)
        done += 1

    if done:
        # A count, never an identity — the whole operation exists to stop us
        # holding identities.
        logger.info("retention sweep scrubbed %s clients", done)
    return done

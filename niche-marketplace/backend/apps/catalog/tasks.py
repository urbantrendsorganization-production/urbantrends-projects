"""Async media processing for listings."""
import io

from celery import shared_task
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from apps.catalog.models import ListingImage

THUMBNAIL_SIZE = (600, 600)


@shared_task
def generate_thumbnail(image_id: int) -> None:
    """Generate a bounded JPEG thumbnail for a ``ListingImage``.

    Idempotent: re-running simply overwrites the thumbnail. Missing rows (e.g.
    the image was deleted before the worker picked the job up) are ignored.
    """
    try:
        listing_image = ListingImage.objects.get(pk=image_id)
    except ListingImage.DoesNotExist:
        return

    with Image.open(listing_image.image) as img:
        # Respect EXIF orientation, then flatten to RGB for JPEG output.
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail(THUMBNAIL_SIZE)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=82, optimize=True)

    name = f"thumb_{listing_image.pk}.jpg"
    # save=True persists the model row with the new thumbnail field.
    listing_image.thumbnail.save(name, ContentFile(buffer.getvalue()), save=True)

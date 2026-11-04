from django.conf import settings
from rest_framework.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


def validate_avatar(upload):
    if upload is None:
        raise ValidationError({"avatar": "An image is required."})
    if upload.size > settings.UPLOAD_MAX_BYTES:
        raise ValidationError({"avatar": "Image is too large."})
    try:
        with Image.open(upload) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 20_000_000:
                raise ValueError
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError({"avatar": "Use a valid JPEG, PNG or WebP image."}) from None
    finally:
        upload.seek(0)
    return upload

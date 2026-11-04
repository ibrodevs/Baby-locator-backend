from pathlib import PurePosixPath
import mimetypes
from django.http import FileResponse, Http404
from django.db.models import Q
from rest_framework.views import APIView
from .models import User
from chat.models import Message
from tracking.models import AroundAudioClip


class PrivateMediaView(APIView):
    def get(self, request, name):
        if ".." in PurePosixPath(name).parts or name.startswith("/"):
            raise Http404
        user = request.user
        ids = [user.pk]
        if user.role == "parent":
            ids.extend(user.children.values_list("pk", flat=True))
        elif user.parent_id:
            ids.append(user.parent_id)
        match = User.objects.filter(pk__in=ids, avatar=name).first()
        field = match.avatar if match else None
        if field is None:
            clip = AroundAudioClip.objects.filter(child_id__in=ids, audio=name).first()
            if clip:
                from subscriptions.services import has_premium_access, premium_required_response
                if not has_premium_access(user):
                    return premium_required_response()
            field = clip.audio if clip else None
        if field is None:
            message = Message.objects.filter(Q(sender_id__in=ids) & Q(receiver_id__in=ids), file=name).first()
            field = message.file if message else None
        if not field:
            raise Http404
        try:
            handle = field.open("rb")
        except (OSError, ValueError):
            raise Http404 from None
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        safe_inline = content_type.startswith(("image/", "audio/", "video/")) and content_type != "image/svg+xml"
        response = FileResponse(handle, content_type=content_type if safe_inline else "application/octet-stream", as_attachment=not safe_inline)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

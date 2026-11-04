from django.core.management.base import BaseCommand
from django.conf import settings
from django.db.models import FileField
from django.apps import apps
from pathlib import Path
import time


class Command(BaseCommand):
    help = "List orphaned private local-media count; --apply removes only unreferenced files."
    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
    def handle(self, *args, **options):
        referenced = set()
        for model in apps.get_models():
            for field in model._meta.fields:
                if isinstance(field, FileField):
                    referenced.update(str(v) for v in model.objects.values_list(field.name, flat=True) if v)
        root = Path(settings.MEDIA_ROOT).resolve()
        # Avoid racing files saved by an upload whose DB transaction has not committed.
        cutoff = time.time() - 3600
        orphans = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink() and p.stat().st_mtime < cutoff and str(p.relative_to(root)) not in referenced and p.name != ".gitkeep"]
        if options["apply"]:
            for path in orphans:
                path.unlink()
        self.stdout.write(f"Orphan private media: {len(orphans)}; removed={bool(options['apply'])}")

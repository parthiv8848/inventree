import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from part.models import Part

class Command(BaseCommand):
    help = "Refresh pricing for all parts in the database"

    def handle(self, *args, **options):
        api_url = "http://localhost:8000/api/part/{}/pricing/"  # Update with your InvenTree base URL if different
        token = "inv-1961b50213e8470b06e0c5fb93b9cf6c49d2b01d-20250826"  # Replace with your actual API token

        headers = {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json"
        }

        parts = Part.objects.all()
        total = parts.count()
        self.stdout.write(self.style.NOTICE(f"Refreshing pricing for {total} parts..."))

        for i, part in enumerate(parts, start=1):
            self.stdout.write(f"[{i}/{total}] Updating pricing for {part.pk} - {part.name}")

            url = api_url.format(part.pk)
            response = requests.patch(url, json={"update": True}, headers=headers)

            if response.status_code == 200:
                self.stdout.write(self.style.SUCCESS(f"  ✅ Updated pricing for {part.pk}"))
            else:
                self.stderr.write(self.style.ERROR(f"  ❌ Failed to update {part.pk}: {response.status_code}"))

        self.stdout.write(self.style.SUCCESS("✅ Pricing update complete"))

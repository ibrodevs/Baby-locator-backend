import json
import math
from urllib.parse import urlencode
from urllib.request import urlopen
from django.conf import settings
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle


class ReverseGeocodeView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'geocoding'

    def get(self, request):
        try:
            lat, lng = float(request.query_params['lat']), float(request.query_params['lng'])
            if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            return Response({'detail': 'Invalid coordinates.'}, status=400)
        if not settings.GOOGLE_GEOCODING_API_KEY:
            return Response({'detail': 'Optional server geocoding is disabled.'}, status=503)
        key = f'geocode:{round(lat,4)}:{round(lng,4)}'
        address = cache.get(key)
        if address is None:
            try:
                query = urlencode({'latlng': f'{lat},{lng}', 'key': settings.GOOGLE_GEOCODING_API_KEY})
                with urlopen('https://maps.googleapis.com/maps/api/geocode/json?' + query, timeout=2) as response:
                    data = json.loads(response.read(1024*1024))
                results = data.get('results', [])
                address = str(results[0].get('formatted_address', '')) if results else ''
            except Exception:
                return Response({'detail': 'Address lookup is temporarily unavailable.'}, status=503)
            cache.set(key, address, 3600)
        return Response({'address': address})

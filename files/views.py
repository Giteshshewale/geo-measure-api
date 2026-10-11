from pathlib import Path

from django.db.models import Count, Sum
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import GeoFeature, GeoFile
from .serializers import (EXTENSION_TO_TYPE, FeatureSerializer, GeoFileSerializer,
                          GeoFileUploadSerializer, MeasurementSerializer)
from .services.processing import process_geofile


class GeoFileViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                     mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = GeoFile.objects.all()
    serializer_class = GeoFileSerializer

    def create(self, request, *args, **kwargs):
        """POST /api/files/ - upload and synchronously process a .zip (Shapefile) or .kml."""
        up = GeoFileUploadSerializer(data=request.data)
        up.is_valid(raise_exception=True)
        f = up.validated_data['file']

        geofile = GeoFile.objects.create(
            file=f,
            filename=Path(f.name).name,
            file_type=EXTENSION_TO_TYPE[Path(f.name).suffix.lower()],
        )
        process_geofile(geofile, fallback_crs=up.validated_data.get('crs'))

        code = status.HTTP_201_CREATED if geofile.status == GeoFile.Status.COMPLETED \
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(GeoFileSerializer(geofile).data, status=code)

    def _require_completed(self, geofile):
        if geofile.status != GeoFile.Status.COMPLETED:
            raise ValidationError({'detail': f'File is {geofile.status}: {geofile.error_message or "not ready"}'})

    @action(detail=True, methods=['get'])
    def features(self, request, pk=None):
        """GET /api/files/{id}/features/ - geometry, CRS and attributes per feature."""
        geofile = self.get_object()
        self._require_completed(geofile)
        qs = geofile.features.all()
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(FeatureSerializer(page, many=True).data)

    @action(detail=True, methods=['get'])
    def measurements(self, request, pk=None):
        """GET /api/files/{id}/measurements/?geometry_type=Polygon - per-feature measurements + summary."""
        geofile = self.get_object()
        self._require_completed(geofile)
        qs = geofile.features.all()
        if gt := request.query_params.get('geometry_type'):
            qs = qs.filter(geometry_type__iexact=gt)

        page = self.paginate_queryset(qs)
        response = self.get_paginated_response(MeasurementSerializer(page, many=True).data)

        ok = geofile.features.filter(measurement_status=GeoFeature.MeasurementStatus.OK)
        by_status = dict(geofile.features.values_list('measurement_status').annotate(n=Count('id')))
        response.data['file_id'] = str(geofile.pk)
        response.data['summary'] = {
            'feature_count': geofile.feature_count,
            'total_area_square_meters': ok.filter(measurement_type='area').aggregate(s=Sum('measurement_value'))['s'] or 0.0,
            'total_length_meters': ok.filter(measurement_type='length').aggregate(s=Sum('measurement_value'))['s'] or 0.0,
            'by_status': by_status,
        }
        return response

from pathlib import Path

from django.conf import settings
from pyproj import CRS
from pyproj.exceptions import CRSError
from rest_framework import serializers

from .models import GeoFeature, GeoFile

EXTENSION_TO_TYPE = {'.zip': GeoFile.FileType.SHAPEFILE, '.kml': GeoFile.FileType.KML}


class GeoFileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    crs = serializers.CharField(
        required=False, allow_blank=True,
        help_text='Optional. Only used if the file itself carries no CRS (e.g. shapefile without .prj).',
    )

    def validate_file(self, f):
        ext = Path(f.name).suffix.lower()
        if ext not in EXTENSION_TO_TYPE:
            raise serializers.ValidationError('Unsupported file type. Upload a .zip (Shapefile) or .kml file.')
        if f.size > settings.MAX_UPLOAD_BYTES:
            raise serializers.ValidationError(f'File too large (max {settings.MAX_UPLOAD_BYTES // 1024 // 1024} MB).')
        return f

    def validate_crs(self, value):
        if not value:
            return None
        try:
            CRS.from_user_input(value)
        except CRSError:
            raise serializers.ValidationError('Unrecognised CRS. Use e.g. "EPSG:4326".')
        return value


class GeoFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFile
        fields = ['id', 'filename', 'file_type', 'feature_count', 'crs', 'status', 'error_message', 'created_at']


class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFeature
        fields = ['index', 'layer', 'geometry_type', 'geometry', 'crs', 'properties']


class MeasurementSerializer(serializers.ModelSerializer):
    feature_index = serializers.IntegerField(source='index')
    measurement = serializers.SerializerMethodField()

    class Meta:
        model = GeoFeature
        fields = ['feature_index', 'layer', 'geometry_type', 'crs', 'measurement']

    def get_measurement(self, obj):
        return {
            'status': obj.measurement_status,
            'type': obj.measurement_type,
            'value': obj.measurement_value,
            'unit': obj.measurement_unit,
            'projected_crs': obj.measurement_crs,
            'message': obj.measurement_message,
        }

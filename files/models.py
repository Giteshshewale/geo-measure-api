import uuid

from django.db import models


class GeoFile(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING'
        PROCESSING = 'PROCESSING'
        COMPLETED = 'COMPLETED'
        FAILED = 'FAILED'

    class FileType(models.TextChoices):
        SHAPEFILE = 'SHAPEFILE'
        KML = 'KML'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to='uploads/%Y/%m/%d/')
    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=16, choices=FileType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    crs = models.CharField(max_length=64, blank=True, default='')
    feature_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.filename} ({self.status})'


class GeoFeature(models.Model):
    """One feature of an uploaded file, with its measurement stored alongside."""

    class MeasurementStatus(models.TextChoices):
        OK = 'OK'                      # measurement calculated
        NOT_REQUIRED = 'NOT_REQUIRED'  # e.g. Point
        UNSUPPORTED = 'UNSUPPORTED'    # geometry type we don't measure
        SKIPPED = 'SKIPPED'            # null / empty geometry
        ERROR = 'ERROR'                # reprojection or calculation failed

    file = models.ForeignKey(GeoFile, related_name='features', on_delete=models.CASCADE)
    index = models.PositiveIntegerField()
    layer = models.CharField(max_length=255, blank=True, default='')
    geometry_type = models.CharField(max_length=32)
    geometry = models.JSONField(null=True)       # GeoJSON, in the *source* CRS
    crs = models.CharField(max_length=64)
    properties = models.JSONField(default=dict)

    measurement_type = models.CharField(max_length=16, null=True, blank=True)  # 'area' | 'length'
    measurement_value = models.FloatField(null=True, blank=True)
    measurement_unit = models.CharField(max_length=32, null=True, blank=True)
    measurement_crs = models.CharField(max_length=128, null=True, blank=True)
    measurement_status = models.CharField(max_length=16, choices=MeasurementStatus.choices)
    measurement_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['index']
        constraints = [models.UniqueConstraint(fields=['file', 'index'], name='unique_feature_index_per_file')]

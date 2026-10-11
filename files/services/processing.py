"""Orchestrates: read file -> measure each feature -> persist."""
import logging
from pathlib import Path

from django.db import transaction
from shapely.geometry import mapping

from ..models import GeoFeature, GeoFile
from .crs import crs_label
from .measurements import measure
from .readers import GeoFileError, read_features

logger = logging.getLogger(__name__)
BATCH = 500


def process_geofile(geofile: GeoFile, fallback_crs: str | None = None) -> GeoFile:
    geofile.status = GeoFile.Status.PROCESSING
    geofile.save(update_fields=['status'])
    try:
        raw_features = read_features(Path(geofile.file.path), geofile.file_type, fallback_crs)

        rows = []
        for rf in raw_features:
            m = measure(rf.geometry, rf.crs)
            rows.append(GeoFeature(
                file=geofile,
                index=rf.index,
                layer=rf.layer,
                geometry_type=rf.geometry.geom_type if rf.geometry is not None else 'None',
                geometry=mapping(rf.geometry) if rf.geometry is not None and not rf.geometry.is_empty else None,
                crs=crs_label(rf.crs),
                properties=rf.properties,
                measurement_type=m.type,
                measurement_value=m.value,
                measurement_unit=m.unit,
                measurement_crs=m.projected_crs,
                measurement_status=m.status,
                measurement_message=m.message,
            ))

        crs_values = {r.crs for r in rows}
        with transaction.atomic():
            GeoFeature.objects.bulk_create(rows, batch_size=BATCH)
            geofile.feature_count = len(rows)
            geofile.crs = crs_values.pop() if len(crs_values) == 1 else ('MIXED' if crs_values else '')
            geofile.status = GeoFile.Status.COMPLETED
            geofile.error_message = ''
            geofile.save()
    except GeoFileError as exc:
        _fail(geofile, str(exc))
    except Exception:  # unexpected: log details, show generic message
        logger.exception('Unexpected error processing GeoFile %s', geofile.pk)
        _fail(geofile, 'Unexpected error while processing file.')
    return geofile


def _fail(geofile: GeoFile, message: str) -> None:
    geofile.status = GeoFile.Status.FAILED
    geofile.error_message = message
    geofile.save(update_fields=['status', 'error_message'])

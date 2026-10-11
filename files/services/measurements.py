"""Measurement calculation. Never measures in degrees: always in a local projected CRS."""
from dataclasses import dataclass

import math
from pyproj import CRS
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from .crs import WGS84, crs_label, get_transformer, laea_crs_for, utm_crs_for

AREA_TYPES = {'Polygon', 'MultiPolygon'}
LENGTH_TYPES = {'LineString', 'MultiLineString'}
NO_MEASURE_TYPES = {'Point', 'MultiPoint'}


@dataclass
class Measurement:
    status: str                      # matches GeoFeature.MeasurementStatus values
    type: str | None = None          # 'area' | 'length'
    value: float | None = None
    unit: str | None = None
    projected_crs: str | None = None
    message: str | None = None


def _reproject(geom: BaseGeometry, src: CRS, dst: CRS) -> BaseGeometry:
    t = get_transformer(src.to_wkt(), dst.to_wkt())
    return transform(t.transform, geom)


def measure(geom: BaseGeometry | None, source_crs: CRS) -> Measurement:
    if geom is None or geom.is_empty:
        return Measurement('SKIPPED', message='Null or empty geometry.')

    gtype = geom.geom_type
    if gtype in NO_MEASURE_TYPES:
        return Measurement('NOT_REQUIRED', message=f'No measurement defined for {gtype}.')
    if gtype not in AREA_TYPES | LENGTH_TYPES:
        return Measurement('UNSUPPORTED', message=f'Measurement not supported for geometry type {gtype}.')

    try:
        # 1. Normalise to WGS84 so we can pick a local projection from lon/lat.
        #    (Handles projected source CRSs, e.g. a shapefile in feet, uniformly.)
        wgs = geom if source_crs == WGS84 else _reproject(geom, source_crs, WGS84)
        c = wgs.centroid
        lon, lat = c.x, c.y
        if not (math.isfinite(lon) and math.isfinite(lat)) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return Measurement('ERROR', message='Coordinates are outside valid longitude/latitude ranges.')

        # 2. Area -> equal-area projection; length -> UTM (conformal, <0.04% scale error in-zone).
        if gtype in AREA_TYPES:
            target, kind, unit = laea_crs_for(lon, lat), 'area', 'square_meter'
        else:
            target, kind, unit = utm_crs_for(lon, lat), 'length', 'meter'

        projected = _reproject(wgs, WGS84, target)
        value = projected.area if kind == 'area' else projected.length
        if not math.isfinite(value):
            return Measurement('ERROR', message='Projection produced non-finite coordinates.')

        label = crs_label(target) if target.to_authority() else 'LAEA centred on feature centroid'
        return Measurement('OK', kind, float(value), unit, label)
    except Exception as exc:  # one bad feature must not fail the whole file
        return Measurement('ERROR', message=f'Measurement failed: {exc}')

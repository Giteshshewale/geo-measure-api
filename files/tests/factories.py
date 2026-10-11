"""Builders for in-memory test/sample files."""
import io
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import shapely
from pyogrio import raw
from shapely.geometry import LineString, Point, Polygon

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>Plot A</name><description>Test plot</description>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
73.8500,18.5000,0 73.8600,18.5000,0 73.8600,18.5100,0 73.8500,18.5100,0 73.8500,18.5000,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>Road B</name>
<LineString><coordinates>73.85,18.50,0 73.86,18.50,0 73.86,18.51,0</coordinates></LineString></Placemark>
<Placemark><name>Gate C</name><Point><coordinates>73.855,18.505,0</coordinates></Point></Placemark>
</Document></kml>
"""

PRJ_4326 = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
            'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')


def kml_bytes() -> bytes:
    return KML.encode()


def shapefile_zip_bytes(geometry_type: str = 'Polygon', crs: str | None = 'EPSG:4326', with_prj: bool = True) -> bytes:
    geoms = {
        'Polygon': [Polygon([(73.85, 18.5), (73.86, 18.5), (73.86, 18.51), (73.85, 18.51)]),
                    Polygon([(73.90, 18.5), (73.91, 18.5), (73.91, 18.51), (73.90, 18.51)])],
        'LineString': [LineString([(73.85, 18.5), (73.86, 18.5)])],
        'Point': [Point(73.85, 18.5)],
    }[geometry_type]
    with tempfile.TemporaryDirectory() as tmp:
        shp = Path(tmp) / 'data.shp'
        raw.write(
            str(shp), geometry=shapely.to_wkb(np.array(geoms, dtype=object)),
            field_data=[np.arange(len(geoms)), np.array([f'f{i}' for i in range(len(geoms))], dtype=object)],
            fields=['id', 'name'], geometry_type=geometry_type, crs=crs if with_prj else None, driver='ESRI Shapefile',
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            for p in Path(tmp).iterdir():
                if not with_prj and p.suffix == '.prj':
                    continue
                zf.write(p, p.name)
        return buf.getvalue()

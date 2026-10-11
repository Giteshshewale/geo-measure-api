from django.test import SimpleTestCase
from pyproj import CRS, Geod
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon

from files.services.crs import utm_crs_for
from files.services.measurements import measure

WGS84 = CRS.from_epsg(4326)
GEOD = Geod(ellps='WGS84')


class MeasureTests(SimpleTestCase):
    def test_polygon_area_matches_geodesic(self):
        poly = Polygon([(73.85, 18.5), (73.86, 18.5), (73.86, 18.51), (73.85, 18.51)])
        m = measure(poly, WGS84)
        truth = abs(GEOD.geometry_area_perimeter(poly)[0])
        self.assertEqual((m.status, m.type, m.unit), ('OK', 'area', 'square_meter'))
        self.assertAlmostEqual(m.value / truth, 1.0, places=3)
        # Sanity: degrees would give ~0.0001, we expect ~1.2 million m2
        self.assertGreater(m.value, 1_000_000)

    def test_line_length_matches_geodesic(self):
        line = LineString([(73.85, 18.5), (73.86, 18.5), (73.86, 18.51)])
        m = measure(line, WGS84)
        self.assertEqual((m.status, m.type, m.unit), ('OK', 'length', 'meter'))
        self.assertEqual(m.projected_crs, 'EPSG:32643')
        self.assertAlmostEqual(m.value / GEOD.geometry_length(line), 1.0, places=3)

    def test_multipolygon_sums_parts(self):
        a = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])
        b = Polygon([(0.02, 0), (0.03, 0), (0.03, 0.01), (0.02, 0.01)])
        total = measure(MultiPolygon([a, b]), WGS84).value
        self.assertAlmostEqual(total, measure(a, WGS84).value + measure(b, WGS84).value, delta=total * 1e-3)

    def test_projected_source_crs(self):
        # 1km x 1km square in UTM 43N must measure ~1,000,000 m2.
        utm = CRS.from_epsg(32643)
        sq = Polygon([(500000, 2000000), (501000, 2000000), (501000, 2001000), (500000, 2001000)])
        self.assertAlmostEqual(measure(sq, utm).value, 1_000_000, delta=1500)

    def test_southern_hemisphere_utm(self):
        self.assertEqual(utm_crs_for(151.2, -33.9).to_epsg(), 32756)

    def test_point_not_required(self):
        self.assertEqual(measure(Point(1, 1), WGS84).status, 'NOT_REQUIRED')

    def test_unsupported_and_empty_are_graceful(self):
        self.assertEqual(measure(GeometryCollection([Point(1, 1)]), WGS84).status, 'UNSUPPORTED')
        self.assertEqual(measure(None, WGS84).status, 'SKIPPED')
        self.assertEqual(measure(Polygon(), WGS84).status, 'SKIPPED')

    def test_out_of_range_coordinates_error(self):
        poly = Polygon([(500, 500), (600, 500), (600, 600), (500, 600)])
        self.assertEqual(measure(poly, WGS84).status, 'ERROR')

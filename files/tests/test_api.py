import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from . import factories

_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA)
class FileApiTests(APITestCase):
    def upload(self, name, content, **extra):
        return self.client.post('/api/files/', {'file': SimpleUploadedFile(name, content), **extra}, format='multipart')

    def test_kml_upload_flow(self):
        r = self.upload('survey.kml', factories.kml_bytes())
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data['status'], r.data['feature_count'], r.data['crs']), ('COMPLETED', 3, 'EPSG:4326'))
        fid = r.data['id']

        info = self.client.get(f'/api/files/{fid}/').data
        self.assertEqual(info['filename'], 'survey.kml')

        m = self.client.get(f'/api/files/{fid}/measurements/').data
        by_type = {x['geometry_type']: x['measurement'] for x in m['results']}
        self.assertEqual(by_type['Polygon']['type'], 'area')
        self.assertEqual(by_type['LineString']['type'], 'length')
        self.assertEqual(by_type['Point']['status'], 'NOT_REQUIRED')
        self.assertGreater(m['summary']['total_area_square_meters'], 1_000_000)
        self.assertEqual(m['summary']['by_status'], {'OK': 2, 'NOT_REQUIRED': 1})

        feats = self.client.get(f'/api/files/{fid}/features/').data['results']
        self.assertEqual(feats[0]['properties']['Name'], 'Plot A')
        self.assertEqual(feats[0]['geometry']['type'], 'Polygon')

    def test_measurement_filter(self):
        fid = self.upload('s.kml', factories.kml_bytes()).data['id']
        r = self.client.get(f'/api/files/{fid}/measurements/?geometry_type=polygon').data
        self.assertEqual(r['count'], 1)

    def test_shapefile_zip(self):
        r = self.upload('parcels.zip', factories.shapefile_zip_bytes('Polygon'))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['feature_count'], 2)
        m = self.client.get(f"/api/files/{r.data['id']}/measurements/").data
        self.assertTrue(all(x['measurement']['type'] == 'area' for x in m['results']))

    def test_shapefile_projected_crs(self):
        r = self.upload('p.zip', factories.shapefile_zip_bytes('Polygon', crs='EPSG:32643'))
        # coordinates (73.85, 18.5) as metres in UTM are a tiny polygon, but must process, not crash
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['crs'], 'EPSG:32643')

    def test_shapefile_without_prj_fails_then_succeeds_with_crs(self):
        z = factories.shapefile_zip_bytes('LineString', with_prj=False)
        bad = self.upload('l.zip', z)
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.data['status'], 'FAILED')
        self.assertIn('no CRS', bad.data['error_message'])
        self.assertEqual(self.client.get(f"/api/files/{bad.data['id']}/measurements/").status_code, 400)

        ok = self.upload('l.zip', z, crs='EPSG:4326')
        self.assertEqual(ok.status_code, 201, ok.data)

    def test_rejects_bad_extension(self):
        r = self.upload('x.txt', b'hello')
        self.assertEqual(r.status_code, 400)

    def test_corrupt_inputs_fail_gracefully(self):
        self.assertEqual(self.upload('x.zip', b'not a zip').status_code, 422)
        self.assertEqual(self.upload('x.kml', b'<kml>garbage').status_code, 422)

    def test_missing_file(self):
        self.assertEqual(self.client.post('/api/files/', {}, format='multipart').status_code, 400)

    def test_unknown_id_404(self):
        self.assertEqual(self.client.get('/api/files/00000000-0000-0000-0000-000000000000/').status_code, 404)

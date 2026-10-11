from rest_framework.routers import DefaultRouter

from .views import GeoFileViewSet

router = DefaultRouter()
router.register('files', GeoFileViewSet, basename='file')
urlpatterns = router.urls

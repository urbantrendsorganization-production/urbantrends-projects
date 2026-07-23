from rest_framework.routers import DefaultRouter

from apps.catalog.views import CategoryViewSet, ListingViewSet

app_name = "catalog"

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("listings", ListingViewSet, basename="listing")

urlpatterns = router.urls

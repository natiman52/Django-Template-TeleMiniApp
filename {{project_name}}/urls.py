"""
URL configuration for {{project_name}} project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from apps.users.api import router as user_router
from apps.users.webhooks import telegram_webhook
api = NinjaAPI(
    title="{{project_name}}",
    version="1.0.0",
)
api.add_router("",user_router)
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/webhook/telegram/', telegram_webhook),

    path("api/v1",api.urls),
]

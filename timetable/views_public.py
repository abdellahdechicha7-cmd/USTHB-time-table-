# Placeholder — implemented by the public-site agent.
from django.http import HttpResponse


def home(request):
    return HttpResponse('home')


def space(request, slug, week=None):
    return HttpResponse(slug)

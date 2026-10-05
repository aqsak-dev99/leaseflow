from .fake_gateway import FakeGatewayProvider
from .manual import ManualProvider

PROVIDERS = {provider.name: provider for provider in (ManualProvider(), FakeGatewayProvider())}


def get_provider(name):
    return PROVIDERS[name]

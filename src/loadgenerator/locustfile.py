#!/usr/bin/python
#
# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import random
from locust import FastHttpUser, TaskSet, between
from faker import Faker
import datetime
fake = Faker()


def _init_tracing():
    """Sets up OpenTelemetry, returning a tracer or None if tracing is off.

    The load generator is the root of every trace in the demo: it starts the
    trace and injects the W3C traceparent header, which the frontend picks up.
    Without it each service would start its own disconnected trace and App
    Topology would have no parent/child spans to derive edges from.

    Note this uses the OTLP *HTTP* exporter, not gRPC. Locust monkey-patches
    the world with gevent, and grpcio needs special handling to cooperate with
    that; the HTTP exporter sits on top of requests and just works.
    """
    if os.environ.get("ENABLE_TRACING") != "1":
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider()
        # Endpoint comes from the standard OTEL_EXPORTER_OTLP_ENDPOINT env var.
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        return trace.get_tracer("loadgenerator")
    except Exception as e:  # noqa: BLE001 - never let telemetry break load gen
        print(f"Failed to initialize tracing, continuing without it: {e}")
        return None


tracer = _init_tracing()


def request(l, method, path, *args, **kwargs):
    """Issues an HTTP request wrapped in a CLIENT span with trace context."""
    call = getattr(l.client, method)
    if tracer is None:
        return call(path, *args, **kwargs)

    from opentelemetry import trace
    from opentelemetry.propagate import inject

    with tracer.start_as_current_span(
        f"{method.upper()} {path}",
        kind=trace.SpanKind.CLIENT,
        attributes={"http.request.method": method.upper(), "url.path": path},
    ):
        headers = dict(kwargs.pop("headers", None) or {})
        inject(headers)
        return call(path, *args, headers=headers, **kwargs)

products = [
    '0PUK6V6EV0',
    '1YMWWN1N4O',
    '2ZYFJ3GM2N',
    '66VCHSJNUP',
    '6E92ZMYYFZ',
    '9SIQT8TOJO',
    'L9ECAV7KIM',
    'LS4PSXUNUM',
    'OLJCESPC7Z']

def index(l):
    request(l, "get", "/")

def setCurrency(l):
    currencies = ['EUR', 'USD', 'JPY', 'CAD', 'GBP', 'TRY']
    request(l, "post", "/setCurrency",
        {'currency_code': random.choice(currencies)})

def browseProduct(l):
    request(l, "get", "/product/" + random.choice(products))

def viewCart(l):
    request(l, "get", "/cart")

def addToCart(l):
    product = random.choice(products)
    request(l, "get", "/product/" + product)
    request(l, "post", "/cart", {
        'product_id': product,
        'quantity': random.randint(1,10)})
    
def empty_cart(l):
    request(l, "post", '/cart/empty')

def checkout(l):
    addToCart(l)
    current_year = datetime.datetime.now().year+1
    request(l, "post", "/cart/checkout", {
        'email': fake.email(),
        'street_address': fake.street_address(),
        'zip_code': fake.zipcode(),
        'city': fake.city(),
        'state': fake.state_abbr(),
        'country': fake.country(),
        'credit_card_number': fake.credit_card_number(card_type="visa"),
        'credit_card_expiration_month': random.randint(1, 12),
        'credit_card_expiration_year': random.randint(current_year, current_year + 70),
        'credit_card_cvv': f"{random.randint(100, 999)}",
    })
    
def logout(l):
    request(l, "get", '/logout')  


class UserBehavior(TaskSet):

    def on_start(self):
        index(self)

    tasks = {index: 1,
        setCurrency: 2,
        browseProduct: 10,
        addToCart: 2,
        viewCart: 3,
        checkout: 1}

class WebsiteUser(FastHttpUser):
    tasks = [UserBehavior]
    wait_time = between(1, 10)

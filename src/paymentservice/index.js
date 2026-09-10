/*
 * Copyright 2018 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

'use strict';

const logger = require('./logger')

if (process.env.DISABLE_PROFILER) {
  logger.info("Profiler disabled.")
} else {
  logger.info("Profiler enabled.")
  require('@google-cloud/profiler').start({
    serviceContext: {
      service: 'paymentservice',
      version: '1.0.0'
    }
  });
}


if (process.env.ENABLE_TRACING == "1") {
  logger.info("Tracing enabled.")

  const { resourceFromAttributes } = require('@opentelemetry/resources');

  const { ATTR_SERVICE_NAME }= require('@opentelemetry/semantic-conventions');

  const { GrpcInstrumentation } = require('@opentelemetry/instrumentation-grpc');
  const { registerInstrumentations } = require('@opentelemetry/instrumentation');
  const opentelemetry = require('@opentelemetry/sdk-node');

  // Must stay in step with @opentelemetry/sdk-trace-base. SDK 2.x replaced
  // ReadableSpan.parentSpanId with parentSpanContext; the old
  // @opentelemetry/exporter-otlp-grpc still read parentSpanId, got undefined,
  // and shipped every span as a trace root. traceId still serialized fine, so
  // the traces looked healthy and only App Topology noticed: no parent means
  // no caller/callee pair, means no runtime edge.
  const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-grpc');

  const collectorAddr = process.env.COLLECTOR_SERVICE_ADDR;
  const collectorUrl = collectorAddr.includes('://') ? collectorAddr : `http://${collectorAddr}`;
  const traceExporter = new OTLPTraceExporter({url: collectorUrl});

  const sdk = new opentelemetry.NodeSDK({
    resource: resourceFromAttributes({
      [ATTR_SERVICE_NAME]: process.env.OTEL_SERVICE_NAME || 'paymentservice',
    }),
    traceExporter: traceExporter,
  });

  registerInstrumentations({
    instrumentations: [new GrpcInstrumentation()]
  });

  sdk.start()
} else {
  logger.info("Tracing disabled.")
}


const path = require('path');
const HipsterShopServer = require('./server');

const PORT = process.env['PORT'];
const PROTO_PATH = path.join(__dirname, '/proto/');

const server = new HipsterShopServer(PROTO_PATH, PORT);

server.listen();

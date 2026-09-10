using System;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using cartservice.cartstore;
using cartservice.services;
using Microsoft.Extensions.Caching.StackExchangeRedis;
using OpenTelemetry.Exporter;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

namespace cartservice
{
    public class Startup
    {
        public Startup(IConfiguration configuration)
        {
            Configuration = configuration;
        }

        public IConfiguration Configuration { get; }
        
        // This method gets called by the runtime. Use this method to add services to the container.
        // For more information on how to configure your application, visit https://go.microsoft.com/fwlink/?LinkID=398940
        public void ConfigureServices(IServiceCollection services)
        {
            string redisAddress = Configuration["REDIS_ADDR"];
            string spannerProjectId = Configuration["SPANNER_PROJECT"];
            string spannerConnectionString = Configuration["SPANNER_CONNECTION_STRING"];
            string alloyDBConnectionString = Configuration["ALLOYDB_PRIMARY_IP"];

            if (!string.IsNullOrEmpty(redisAddress))
            {
                services.AddStackExchangeRedisCache(options =>
                {
                    options.Configuration = redisAddress;
                });
                services.AddSingleton<ICartStore, RedisCartStore>();
            }
            else if (!string.IsNullOrEmpty(spannerProjectId) || !string.IsNullOrEmpty(spannerConnectionString))
            {
                services.AddSingleton<ICartStore, SpannerCartStore>();
            }
            else if (!string.IsNullOrEmpty(alloyDBConnectionString))
            {
                Console.WriteLine("Creating AlloyDB cart store");
                services.AddSingleton<ICartStore, AlloyDBCartStore>();
            }
            else
            {
                Console.WriteLine("Redis cache host(hostname+port) was not specified. Starting a cart service using in memory store");
                services.AddDistributedMemoryCache();
                services.AddSingleton<ICartStore, RedisCartStore>();
            }


            services.AddGrpc();

            ConfigureTracing(services);
        }

        // Emits a SERVER span for every inbound gRPC call, which is what pairs
        // with the caller's CLIENT span to form the frontend -> cartservice and
        // checkoutservice -> cartservice edges in App Topology. ASP.NET Core
        // reads the inbound W3C traceparent header by default, so the spans
        // join the caller's trace rather than starting a new one.
        private void ConfigureTracing(IServiceCollection services)
        {
            if (Configuration["ENABLE_TRACING"] != "1")
            {
                Console.WriteLine("Tracing disabled.");
                return;
            }

            string collectorAddr = Configuration["COLLECTOR_SERVICE_ADDR"];
            if (string.IsNullOrEmpty(collectorAddr))
            {
                Console.WriteLine("Tracing enabled but COLLECTOR_SERVICE_ADDR is not set; traces will not be exported.");
                return;
            }

            string serviceName = Configuration["OTEL_SERVICE_NAME"] ?? "cartservice";
            Console.WriteLine($"Tracing enabled, exporting to {collectorAddr}");

            services.AddOpenTelemetry()
                .ConfigureResource(resource => resource.AddService(serviceName))
                .WithTracing(tracing => tracing
                    .AddAspNetCoreInstrumentation()
                    .AddOtlpExporter(options =>
                    {
                        options.Endpoint = new Uri($"http://{collectorAddr}");
                        options.Protocol = OtlpExportProtocol.Grpc;
                    }));
        }

        // This method gets called by the runtime. Use this method to configure the HTTP request pipeline.
        public void Configure(IApplicationBuilder app, IWebHostEnvironment env)
        {
            if (env.IsDevelopment())
            {
                app.UseDeveloperExceptionPage();
            }

            app.UseRouting();

            app.UseEndpoints(endpoints =>
            {
                endpoints.MapGrpcService<CartService>();
                endpoints.MapGrpcService<cartservice.services.HealthCheckService>();

                endpoints.MapGet("/", async context =>
                {
                    await context.Response.WriteAsync("Communication with gRPC endpoints must be made through a gRPC client. To learn how to create a client, visit: https://go.microsoft.com/fwlink/?linkid=2086909");
                });
            });
        }
    }
}

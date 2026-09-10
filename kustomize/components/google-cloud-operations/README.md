# Integrate Online Boutique with Google Cloud Operations

By default, [Google Cloud Operations](https://cloud.google.com/products/operations) instrumentation is **turned off** for Online Boutique deployments. This includes Monitoring (Stats), Tracing, and Profiler. This means that even if you're running this app on [GKE](https://cloud.google.com/kubernetes-engine), traces (for example) will not be exported to [Google Cloud Trace](https://cloud.google.com/trace).

If you want to re-enable Google Cloud Operations instrumentation, the easiest way is to enable the included kustomize module, which enables traces, metrics, and adds a deployment of the [Open Telemetry Collector](https://opentelemetry.io/docs/collector/) to gather the traces and metrics and forward them to the appropriate Google Cloud backend.

From the `kustomize/` folder at the root level of this repository, execute this command:

```bash
kustomize edit add component components/google-cloud-operations
```

This will update the `kustomize/kustomization.yaml` file which could be similar to:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
- base
components:
- components/google-cloud-operations
```

You can locally render these manifests by running `kubectl kustomize .` as well as deploying them by running `kubectl apply -k .`.

You will also need to make sure that you have the associated Google APIs enabled in your Google Cloud project:

```bash
PROJECT_ID=<your-gcp-project-id>
gcloud services enable \
    monitoring.googleapis.com \
    cloudtrace.googleapis.com \
    cloudprofiler.googleapis.com \
    telemetry.googleapis.com \
    --project ${PROJECT_ID}
```

In addition to that, the collector's Kubernetes ServiceAccount needs permission
to write telemetry. With Workload Identity you can grant the roles directly to
the Kubernetes ServiceAccount principal, with no Google Service Account in the
middle:

```bash
PROJECT_ID=<your-gcp-project-id>
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')
NAMESPACE=<your-namespace>   # e.g. default

MEMBER="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/${NAMESPACE}/sa/opentelemetrycollector"

# Writes traces via the Telemetry (OTLP) API.
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member "${MEMBER}" --role roles/telemetry.writer

# Required because the Telemetry API bills quota against the project.
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member "${MEMBER}" --role roles/serviceusage.serviceUsageConsumer

# Only needed for the metrics pipeline, which still uses the googlecloud exporter.
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member "${MEMBER}" --role roles/monitoring.metricWriter
```

## Changes

When enabling this kustomize module, most services will be patched with a configuration similar to the following:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: productcatalogservice
spec:
  template:
    spec:
      containers:
        - name: server
          env:
          - name: COLLECTOR_SERVICE_ADDR
            value: "opentelemetrycollector:4317"
          - name: ENABLE_STATS
            value: "1"
          - name: ENABLE_TRACING
            value: "1"
```

This patch sets environment variables to enable export of stats and tracing, as well as a variable to tell the service how to reach the new collector deployment.

## OpenTelemetry Collector

Currently, this component adds a single collector service which collects traces and metrics from individual services and forwards them to the appropriate Google Cloud backend.

![Collector Architecture Diagram](collector-model.png)

If you wish to experiment with different backends, you can modify the appropriate lines in [otel-collector.yaml](otel-collector.yaml) to export traces or metrics to a different backend.  See the [OpenTelemetry docs](https://opentelemetry.io/docs/collector/configuration/) for more details.

## App Topology / runtime edges

App Topology draws a runtime edge between two workloads when it can pair a
caller's span with a callee's span *and* resolve both spans back to a concrete
GKE workload. Resolution is by resource attribute, and the full set must be
present on the span:

| Attribute | Supplied by |
| --- | --- |
| `cloud.provider` (`"gcp"`) | `resourcedetection` processor, `gcp` detector |
| `cloud.account.id` (project **ID**, not number) | `resourcedetection` |
| `cloud.region` *or* `cloud.availability_zone` | `resourcedetection` (regional vs zonal cluster) |
| `k8s.cluster.name` | `resourcedetection` |
| `k8s.namespace.name` | `k8sattributes` processor |
| `k8s.deployment.name` (or statefulset/daemonset/cronjob) | `k8sattributes` processor |

Two things in this component exist specifically to satisfy that, and are easy to
break by accident:

1. **Traces are exported over OTLP to `telemetry.googleapis.com`, not with the
   `googlecloud` exporter.** The legacy Cloud Trace API rewrites OpenTelemetry
   resource attributes (into `g.co/r/...` span labels), and App Topology matches
   on the raw OTLP attribute names. Switching the traces pipeline back to the
   `googlecloud` exporter will keep traces flowing to Cloud Trace and silently
   remove every runtime edge.
2. **The collector needs RBAC.** The `k8sattributes` processor maps the sending
   pod's connection IP to its pod, then walks pod → ReplicaSet → Deployment. That
   requires read access to `pods`, `namespaces`, `nodes` and `replicasets`, which
   the ClusterRole in this component grants.

Edges also need trace context to actually propagate. Every service here installs
the W3C `tracecontext` propagator; if a service starts a fresh trace instead of
continuing the caller's, its spans have no parent and no edge is produced.

## Workload Identity

If you are running this sample on GKE, your GKE cluster may be configured to use [Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity) to manage access to Google Cloud APIs (like Cloud Trace). If this is the case, you may not see traces properly exported, or may see an error message like `failed to export to Google Cloud Trace: rpc error: code = PermissionDenied desc = The caller does not have permission` logged by your `opentelemetrycollector` Pod(s). In order to export traces with such a setup, you need to associate the Kubernetes [ServiceAccount](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/) (`default/default`) with your [default compute service account](https://cloud.google.com/compute/docs/access/service-accounts#default_service_account) on Google Cloud (or a custom Google Cloud service account you may create for this purpose).

* To get the email address associated with your Google service account, check in the IAM section of the Cloud Console.  Or run the following command in your terminal:

```bash
gcloud iam service-accounts list
```

* Then, allow the Kubernetes service account to act as your Google service account with the following command (using your own `PROJECT_ID` and the `GSA_EMAIL` you found in the previous step):

```bash
gcloud iam service-accounts add-iam-policy-binding ${GSA_EMAIL} \
  --role roles/iam.workloadIdentityUser \
  --member "serviceAccount:${PROJECT_ID}.svc.id.goog[default/default]"
```

* Annotate your Kubernetes service account (`default/default` for the `default` namespace) to use the Google IAM service account:

```bash
kubectl annotate serviceaccount default \
  iam.gke.io/gcp-service-account=${GSA_EMAIL}
```

* Finally, restart your `opentelemetrycollector` deployment to reflect the new settings:

```bash
kubectl rollout restart deployment opentelemetrycollector
```

When the new Pod rolls out, you should start to see traces appear in the cloud console.

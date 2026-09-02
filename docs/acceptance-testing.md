# SensorTrain v1.0 acceptance testing

The v1.0 release was accepted only after the complete sensor, bridge, application, control, and recovery path was exercised on the production Raspberry Pi 5 / Pico 2 W system.

## Hardware smoke test

The following devices operated simultaneously on the Pico breadboard prototype:

- BNO085 on shared I2C
- BME280 on shared I2C
- two DS18B20 probes on one 1-Wire bus
- DRV5032 Hall sensor
- two MOSFET-driven fans

## Telemetry

Pass criteria:

- Pico emits valid `sensortrain.telemetry.v1` NDJSON.
- Bridge reads `/dev/sensortrain-pico` without root privileges.
- Bridge forwards telemetry to MicroShift.
- Dashboard updates without manual refresh.
- Individual sensor read failures degrade fields to null/error state without crashing the telemetry loop.

Result: **PASS**.

## Fan control

Tested levels independently for intake and exhaust:

- 0%
- 25%
- 50%
- 75%
- 100%

Additional startup characterization established that 25% can sustain a spinning fan but does not reliably start a stopped fan. Production firmware therefore applies 100% for 0.5 seconds when transitioning from stopped directly to 25%, then settles at 25%.

Control acknowledgements were verified through `sensortrain.control.ack.v1` and bridge retry behavior.

Result: **PASS**.

## Hall sensor

The DRV5032 active-low input was verified through the complete telemetry path and dashboard indicator.

Result: **PASS**.

## Dashboard history

Eight simultaneous graph panels were accepted:

- temperature
- humidity
- pressure
- acceleration
- gyroscope
- orientation
- Hall state
- fan output

A common selector updates all graphs for 1, 5, 10, 20, or 30 minute windows. The accepted desktop layout fits without scrolling.

Result: **PASS**.

## System health indicators

Independent status behavior was tested for PICO, BRIDGE, and CLUSTER.

### Normal operation

Expected: all three indicators healthy and overall state LIVE.

Result: **PASS**.

### Bridge stopped

Procedure: stop `sensortrain-bridge.service`.

Expected after freshness thresholds:

- PICO unhealthy
- BRIDGE unhealthy
- CLUSTER healthy
- dashboard overall state becomes stale

Restarting the bridge must restore all indicators without refreshing the browser.

Result: **PASS**.

### Pico unplugged

Expected:

- PICO unhealthy
- BRIDGE healthy
- CLUSTER healthy
- bridge service remains running

Reconnect must automatically restore telemetry and PICO health without browser refresh.

Result: **PASS**.

### Web pod replacement

Procedure: delete the running `sensortrain-web` pod and allow the Deployment to replace it.

Expected:

- replacement pod becomes Ready
- browser reconnects without manual refresh
- PICO, BRIDGE, and CLUSTER return healthy
- Pico firmware 0.3.0 telemetry resumes
- history restarts empty
- desired fan state resets

Result: **PASS**.

## Cluster readiness

The web pod service account directly queried `https://kubernetes.default.svc/readyz` using the mounted service-account CA and token and received HTTP 200 with body `ok`. No additional RBAC changes were required on the accepted installation.

Result: **PASS**.

## Storage/platform

MicroShift storage was validated with the default `topolvm-provisioner` StorageClass. A test PVC bound successfully and was reclaimed successfully.

The MicroShift node, OVN, DNS, ingress, service CA, CSI, and LVMS components were healthy at acceptance.

Result: **PASS**.

## v1.0 accepted behavior

The following are intentional characteristics, not defects:

- dashboard history is RAM-only
- history resets on web pod restart/replacement
- desired fan state resets on web pod restart/replacement
- the host bridge uses the Service ClusterIP from local configuration
- the Raspberry Pi 5 platform is not a Red Hat-supported hardware target

The tagged `v1.0.0` release represents the accepted baseline before later documentation, PCB, LED, and mechanical refinements.

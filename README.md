# SensorTrain

SensorTrain is a Raspberry Pi 5 / Raspberry Pi Pico 2 W sensor and compute platform designed to operate inside a LEGO train.

The Raspberry Pi 5 runs Red Hat Enterprise Linux 9.8 with the Red Hat build of MicroShift 4.22 on a custom Raspberry Pi 6.18 kernel. A Pico 2 W handles physical sensor acquisition and fan control, with telemetry bridged into a MicroShift-hosted web dashboard.

## Hardware

### Compute
- Raspberry Pi 5
- Official Raspberry Pi 5 Active Cooler
- 128 GB 2242 NVMe SSD
- Raspberry Pi Pico 2 W

### Sensors
- BNO085 IMU
- BME280 environmental sensor
- 2 x DS18B20 temperature sensors
- DRV5032 Hall-effect sensor

### Cooling
- 2 x 30 mm fans
- MOSFET fan drivers
- PWM levels: 0%, 25%, 50%, 75%, 100%
- 0.5-second full-power startup kick when starting at 25%

## Software architecture

```text
Pico 2 W
    |
    | USB serial / NDJSON
    v
sensortrain-bridge
    |
    | HTTP
    v
MicroShift / sensortrain-web
    |
    v
Browser dashboard
```

The dashboard provides:

- live environmental and temperature gauges
- acceleration, gyroscope, and orientation telemetry
- Hall sensor indication
- independent intake/exhaust fan control
- simultaneous rolling history graphs
- 1, 5, 10, 20, and 30 minute history windows
- independent PICO, BRIDGE, and CLUSTER health indicators

History is intentionally stored in RAM and resets when the web application restarts.

## Documentation

- [Architecture](docs/architecture.md)
- [Hardware](docs/hardware.md)
- [Installation](docs/installation.md)
- [v1.0 acceptance testing](docs/acceptance-testing.md)
- [MicroShift deployment](deploy/microshift/README.md)
- [Raspberry Pi / RHEL / MicroShift platform notes](platform/raspberry-pi-rhel-microshift.md)

## Repository layout

- `pico/` - Pico 2 W CircuitPython firmware
- `bridge/` - Raspberry Pi host serial/HTTP bridge and host integration
- `web/` - MicroShift dashboard application
- `deploy/` - deployment manifests and deployment notes
- `docs/` - architecture, hardware, installation, and acceptance documentation
- `platform/` - Raspberry Pi / RHEL / MicroShift platform notes
- `releases/` - release records

## Current release

SensorTrain v1.0

- Pico firmware: 0.3.0
- CircuitPython: 10.2.1
- RHEL: 9.8
- MicroShift: 4.22
- Kubernetes: 1.35

The `v1.0.0` tag is the frozen accepted baseline. Development and documentation continue on `main`.

## Support note

The RHEL userspace and MicroShift packages used by this project are genuine Red Hat software. Raspberry Pi 5 is not a supported Red Hat hardware target for this configuration, and the project relies on a custom Raspberry Pi kernel and boot arrangement.

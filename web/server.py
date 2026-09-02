import json
import ssl
import urllib.request
import time
from collections import deque
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

latest = None
received_at = None

# Roughly 45-50 minutes at the current telemetry
# cadence, providing headroom above the 30-minute
# graph window.
history = deque(maxlen=1200)

# Independent system-health state.
bridge_heartbeat_at = None

cluster_check_at = 0.0
cluster_ready = False
cluster_error = None

PICO_FRESH_SECONDS = 8.0
BRIDGE_FRESH_SECONDS = 6.0
CLUSTER_CACHE_SECONDS = 3.0

latest_control = {
    "id": 0,
    "command": None
}

def empty_telemetry():
    return {
        "schema": "sensortrain.telemetry.v1",
        "firmware": None,
        "status": "waiting",
        "seq": None,
        "uptime_s": None,
        "environment": {
            "temperature_c": None,
            "pressure_hpa": None,
            "humidity_pct": None
        },
        "temperatures": {
            "compute_c": None,
            "exhaust_c": None
        },
        "motion": {
            "accel_x": None,
            "accel_y": None,
            "accel_z": None,
            "gyro_x": None,
            "gyro_y": None,
            "gyro_z": None,
            "quat_i": None,
            "quat_j": None,
            "quat_k": None,
            "quat_real": None
        },
        "hall": {
            "active": False
        },
        "fans": {
            "intake_pct": 0,
            "exhaust_pct": 0
        },
        "errors": []
    }

PAGE = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport"
        content="width=device-width, initial-scale=1">

  <title>SensorTrain</title>

  <style>
    :root {
      font-family:
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

      color-scheme: dark;
    }

    * {
      box-sizing: border-box;
    }

    html,
    body {
      margin: 0;
      width: 100%;
      height: 100%;
    }

    body {
      background: #101418;
      color: #e8edf2;
      overflow: hidden;
    }

    button {
      font: inherit;
    }

    .page {
      width: min(1600px, 100%);
      height: 100vh;
      margin: 0 auto;
      padding: 10px 14px;

      display: grid;
      grid-template-rows:
        auto
        122px
        168px
        minmax(360px, 1fr);

      gap: 9px;
    }


    /* ============================================
       Header
       ============================================ */

    .header {
      min-height: 46px;

      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;

      padding: 4px 3px;
    }

    .brand {
      display: flex;
      align-items: baseline;
      gap: 12px;
    }

    .brand-name {
      font-size: 1.45rem;
      font-weight: 850;
      letter-spacing: -0.02em;
    }

    .brand-subtitle {
      color: #81909c;
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .header-status {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 14px;
      flex-wrap: wrap;

      font-size: 0.8rem;
      color: #9aa8b4;
    }

    .header-value {
      color: #dce4ea;
      font-weight: 750;
    }

    .system-strip {
      display: flex;
      align-items: center;
      gap: 8px;

      padding-right: 3px;

      font-size: 0.65rem;
      font-weight: 800;
      letter-spacing: 0.05em;
    }

    .system-item {
      display: flex;
      align-items: center;
      gap: 4px;

      color: #7f8d98;
      white-space: nowrap;
    }

    .system-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;

      background: #4a555e;
      box-shadow:
        0 0 0 1px #5f6b74;
    }

    .system-dot.ok {
      background: #58c98d;
      box-shadow:
        0 0 5px rgba(
          88,
          201,
          141,
          0.65
        );
    }

    .system-dot.bad {
      background: #db6c65;
      box-shadow:
        0 0 5px rgba(
          219,
          108,
          101,
          0.55
        );
    }

    .system-dot.unknown {
      background: #58636c;
      box-shadow: none;
    }

    .status-badge {
      border-radius: 999px;
      padding: 5px 11px;

      font-size: 0.76rem;
      font-weight: 850;
      letter-spacing: 0.08em;
    }

    .status-badge.live {
      background: #163c2c;
      color: #73dfa8;
    }

    .status-badge.waiting {
      background: #34383d;
      color: #bbc4cc;
    }

    .status-badge.stale {
      background: #4c3820;
      color: #ffc66d;
    }

    .status-badge.degraded {
      background: #4b2927;
      color: #ff9188;
    }

    .error-strip {
      display: none;
      position: absolute;
      left: 14px;
      right: 14px;
      top: 54px;

      border: 1px solid #75423e;
      background: #3b2523;
      color: #ffb0a8;

      border-radius: 7px;
      padding: 6px 10px;

      font-size: 0.75rem;
      z-index: 10;
    }


    /* ============================================
       Shared panels
       ============================================ */

    .panel {
      background: #171d23;
      border: 1px solid #2b343d;
      border-radius: 11px;
      min-width: 0;
    }

    .panel-title {
      color: #9eabb7;

      font-size: 0.72rem;
      font-weight: 850;
      letter-spacing: 0.09em;
      text-transform: uppercase;
    }


    /* ============================================
       Gauges
       ============================================ */

    .gauges {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 9px;
      min-width: 0;
    }

    .gauge-card {
      appearance: none;
      width: 100%;
      min-width: 0;

      border: 1px solid #2b343d;
      border-radius: 11px;
      background: #171d23;
      color: #e8edf2;

      padding: 8px 10px 7px;

      display: grid;
      grid-template-rows: auto 1fr auto;

      cursor: pointer;
      text-align: center;
    }

    .gauge-card:hover {
      border-color: #53616d;
      background: #1a2128;
    }

    .gauge-card:focus-visible {
      outline: 2px solid #6e9cca;
      outline-offset: 2px;
    }

    .gauge-title {
      color: #9eabb7;

      font-size: 0.7rem;
      font-weight: 850;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .gauge {
      position: relative;
      height: 98px;
      margin-top: -3px;
    }

    .gauge svg {
      width: 100%;
      height: 100%;
      overflow: visible;
    }

    .gauge-track {
      fill: none;
      stroke: #27313a;
      stroke-width: 11;
      stroke-linecap: round;
    }

    .gauge-value-arc {
      fill: none;
      stroke: #649bd2;
      stroke-width: 11;
      stroke-linecap: round;

      stroke-dasharray: 0 100;
      transition: stroke-dasharray 0.25s ease;
    }

    .gauge-scale-tick {
      stroke: #7b8994;
      stroke-width: 1.2;
    }

    .gauge-scale-label {
      fill: #8d9aa5;
      font-size: 6px;
      font-weight: 650;
      font-family:
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
    }

    .gauge-scale-label.pressure {
      font-size: 5px;
    }

    .gauge-scale-tick.major {
      stroke: #aab6c0;
      stroke-width: 1.7;
    }

    .gauge-number {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 1px;

      font-size: 1.55rem;
      line-height: 1;
      font-weight: 850;
      letter-spacing: -0.04em;
    }

    .gauge-unit {
      margin-left: 3px;

      color: #9aa8b4;
      font-size: 0.7rem;
      font-weight: 650;
    }


    /* ============================================
       Middle instrument row
       ============================================ */

    .instruments {
      display: grid;
      grid-template-columns:
        1.25fr
        0.78fr
        0.48fr
        1.8fr;

      gap: 9px;
      min-height: 0;
    }

    .motion-panel,
    .orientation-panel,
    .hall-panel,
    .fan-panel {
      padding: 10px 12px;
    }

    .motion-columns {
      height: calc(100% - 22px);

      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 15px;

      align-items: center;
    }

    .motion-group-title {
      color: #75838f;
      font-size: 0.67rem;
      font-weight: 800;
      letter-spacing: 0.07em;
      text-transform: uppercase;

      margin-bottom: 5px;
    }

    .axis-row {
      display: grid;
      grid-template-columns: 20px 1fr;
      align-items: baseline;
      gap: 7px;

      min-height: 31px;
    }

    .axis-label {
      color: #70808c;
      font-size: 0.72rem;
      font-weight: 850;
    }

    .axis-value {
      font-variant-numeric: tabular-nums;
      font-size: 1.03rem;
      font-weight: 720;
    }

    .axis-unit {
      color: #65737e;
      font-size: 0.62rem;
      margin-left: 3px;
    }

    .orientation-values {
      margin-top: 7px;
    }

    .orientation-panel .axis-row {
      min-height: 31px;
    }


    /* ============================================
       Hall
       ============================================ */

    .hall-panel {
      display: grid;
      grid-template-rows: auto 1fr auto;
    }

    .hall-center {
      display: flex;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      gap: 8px;
    }

    .hall-lamp {
      width: 43px;
      height: 43px;
      border-radius: 50%;

      background: #273039;
      border: 4px solid #384550;
    }

    .hall-lamp.clear {
      background: #457963;
      border-color: #63967f;
    }

    .hall-lamp.magnet {
      background: #ce645c;
      border-color: #f1877f;
    }

    .hall-text {
      font-size: 0.9rem;
      font-weight: 850;
      letter-spacing: 0.08em;
    }

    .hall-note {
      color: #65737e;
      text-align: center;
      font-size: 0.62rem;
    }


    /* ============================================
       Fans
       ============================================ */

    .fan-panel {
      min-width: 0;
    }

    .fan-row {
      display: grid;
      grid-template-columns: 68px 1fr 45px;
      gap: 8px;
      align-items: center;

      margin-top: 10px;
    }

    .fan-name {
      color: #9ba8b4;

      font-size: 0.69rem;
      font-weight: 850;
      letter-spacing: 0.08em;
    }

    .fan-levels {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 5px;
      min-width: 0;
    }

    .fan-button {
      appearance: none;

      min-width: 0;
      padding: 7px 3px;

      border: 1px solid #35414c;
      border-radius: 7px;

      background: #1e262d;
      color: #b7c2cb;

      font-size: 0.68rem;
      font-weight: 800;

      cursor: pointer;
    }

    .fan-button:hover:not(:disabled) {
      background: #27323b;
      border-color: #657682;
    }

    .fan-button.actual {
      background: #184b37;
      border-color: #40976e;
      color: #d9f5e7;
    }

    .fan-button:disabled {
      opacity: 0.48;
      cursor: wait;
    }

    .fan-actual {
      text-align: right;

      font-size: 0.81rem;
      font-weight: 850;
      font-variant-numeric: tabular-nums;
    }

    .fan-bottom {
      margin-top: 12px;

      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .control-status {
      color: #788792;
      font-size: 0.67rem;

      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .control-status.confirmed {
      color: #69cf99;
    }

    .control-status.error {
      color: #ff8e85;
    }

    .all-off {
      appearance: none;

      border: 1px solid #8b4c47;
      border-radius: 7px;

      background: #492725;
      color: #ffc1bb;

      padding: 7px 14px;

      font-size: 0.69rem;
      font-weight: 850;

      cursor: pointer;
    }

    .all-off.actual {
      background: #592d29;
      border-color: #cf6a61;
    }


    /* ============================================
       Always-visible history matrix
       ============================================ */

    .history-panel {
      padding: 8px 10px 9px;
      min-height: 0;

      display: grid;
      grid-template-rows: auto 1fr;
      gap: 6px;
    }

    .history-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .history-ranges {
      display: flex;
      gap: 4px;
    }

    .range-button {
      appearance: none;

      border: 1px solid #35414b;
      border-radius: 6px;

      background: #1d252c;
      color: #85939e;

      padding: 4px 7px;

      font-size: 0.63rem;
      font-weight: 800;

      cursor: pointer;
    }

    .range-button.active {
      background: #184b37;
      border-color: #3c9069;
      color: #d9f5e7;
    }

    .mini-chart-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      grid-template-rows: repeat(4, minmax(0, 1fr));

      gap: 6px;

      min-height: 0;
    }

    .mini-chart {
      min-width: 0;
      min-height: 0;

      border: 1px solid #29333c;
      border-radius: 8px;

      background: #141a20;

      padding: 5px 7px 4px;

      display: grid;
      grid-template-rows: auto 1fr;
    }

    .mini-chart.selected {
      border-color: #54738a;
    }

    .mini-chart-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;

      min-height: 17px;
    }

    .mini-chart-title {
      color: #a4b0ba;

      font-size: 0.64rem;
      font-weight: 850;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }

    .mini-legend {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 7px;
      flex-wrap: wrap;

      color: #75848f;
      font-size: 0.56rem;
    }

    .mini-legend-item {
      display: flex;
      align-items: center;
      gap: 3px;
    }

    .mini-swatch {
      width: 10px;
      height: 2px;
      border-radius: 2px;
    }

    .mini-canvas {
      display: block;
      width: 100%;
      height: 100%;
      min-height: 60px;
    }


    /* ============================================
       Compact-height desktop
       ============================================ */

    @media (max-height: 830px) and (min-width: 1000px) {
      .page {
        grid-template-rows:
          auto
          125px
          172px
          minmax(205px, 1fr);
      }

      .gauge {
        height: 76px;
      }

      .gauge-number {
        font-size: 1.35rem;
      }

      .axis-row {
        min-height: 27px;
      }

      .fan-row {
        margin-top: 7px;
      }
    }


    /* ============================================
       Narrow/small screens fall back to scrolling
       ============================================ */

    @media (max-width: 999px),
           (max-height: 690px) {

      body {
        overflow: auto;
      }

      .page {
        height: auto;
        min-height: 100%;
        grid-template-rows: auto;
      }

      .gauges {
        grid-template-columns:
          repeat(2, minmax(0, 1fr));
      }

      .instruments {
        grid-template-columns:
          1fr;
      }

      .history-panel {
        min-height: 340px;
      }

      .history-toolbar {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>

<body>

  <div class="page">

    <header class="header">

      <div class="brand">
        <div class="brand-name">SensorTrain</div>

        <div class="brand-subtitle">
          MicroShift Sensor Platform
        </div>
      </div>

      <div class="header-status">

        <div class="system-strip">

          <span
            class="system-item"
            title="Pico telemetry status">
            <span
              id="systemPico"
              class="system-dot unknown">
            </span>
            PICO
          </span>

          <span
            class="system-item"
            title="Host bridge service status">
            <span
              id="systemBridge"
              class="system-dot unknown">
            </span>
            BRIDGE
          </span>

          <span
            class="system-item"
            title="MicroShift API readiness">
            <span
              id="systemCluster"
              class="system-dot unknown">
            </span>
            CLUSTER
          </span>

        </div>


        <span
          id="statusBadge"
          class="status-badge waiting">
          WAITING
        </span>

        <span>
          FW
          <span
            id="firmware"
            class="header-value">--</span>
        </span>

        <span>
          Seq
          <span
            id="seq"
            class="header-value">--</span>
        </span>

        <span>
          Pico
          <span
            id="uptime"
            class="header-value">--</span>
        </span>

        <span>
          Age
          <span
            id="age"
            class="header-value">--</span>
        </span>

      </div>

    </header>


    <div
      id="errorStrip"
      class="error-strip">
    </div>


    <!-- ==========================================
         Gauges
         ========================================== -->

    <section class="gauges">

      <button
        class="gauge-card"
        type="button"
        onclick="selectHistory('temperature')">

        <div class="gauge-title">
          Compute
        </div>

        <div class="gauge">
          <svg viewBox="0 0 120 70">
            <path
              class="gauge-track"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>

            <path
              id="computeArc"
              class="gauge-value-arc"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>
          </svg>

          <div class="gauge-number">
            <span id="compute">--</span>
            <span class="gauge-unit">°C</span>
          </div>
        </div>

      </button>


      <button
        class="gauge-card"
        type="button"
        onclick="selectHistory('temperature')">

        <div class="gauge-title">
          Exhaust
        </div>

        <div class="gauge">
          <svg viewBox="0 0 120 70">
            <path
              class="gauge-track"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>

            <path
              id="exhaustArc"
              class="gauge-value-arc"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>
          </svg>

          <div class="gauge-number">
            <span id="exhaust">--</span>
            <span class="gauge-unit">°C</span>
          </div>
        </div>

      </button>


      <button
        class="gauge-card"
        type="button"
        onclick="selectHistory('temperature')">

        <div class="gauge-title">
          Ambient
        </div>

        <div class="gauge">
          <svg viewBox="0 0 120 70">
            <path
              class="gauge-track"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>

            <path
              id="ambientArc"
              class="gauge-value-arc"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>
          </svg>

          <div class="gauge-number">
            <span id="ambient">--</span>
            <span class="gauge-unit">°C</span>
          </div>
        </div>

      </button>


      <button
        class="gauge-card"
        type="button"
        onclick="selectHistory('humidity')">

        <div class="gauge-title">
          Humidity
        </div>

        <div class="gauge">
          <svg viewBox="0 0 120 70">
            <path
              class="gauge-track"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>

            <path
              id="humidityArc"
              class="gauge-value-arc"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>
          </svg>

          <div class="gauge-number">
            <span id="humidity">--</span>
            <span class="gauge-unit">%</span>
          </div>
        </div>

      </button>


      <button
        class="gauge-card"
        type="button"
        onclick="selectHistory('pressure')">

        <div class="gauge-title">
          Pressure
        </div>

        <div class="gauge">
          <svg viewBox="0 0 120 70">
            <path
              class="gauge-track"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>

            <path
              id="pressureArc"
              class="gauge-value-arc"
              pathLength="100"
              d="M 10 60 A 50 50 0 0 1 110 60">
            </path>
          </svg>

          <div class="gauge-number">
            <span id="pressure">--</span>
            <span class="gauge-unit">hPa</span>
          </div>
        </div>

      </button>

    </section>


    <!-- ==========================================
         Instruments
         ========================================== -->

    <section class="instruments">

      <div class="panel motion-panel">

        <div class="panel-title">
          Motion
        </div>

        <div class="motion-columns">

          <div>
            <div class="motion-group-title">
              Acceleration
            </div>

            <div class="axis-row">
              <span class="axis-label">X</span>
              <span class="axis-value">
                <span id="accelX">--</span>
                <span class="axis-unit">m/s²</span>
              </span>
            </div>

            <div class="axis-row">
              <span class="axis-label">Y</span>
              <span class="axis-value">
                <span id="accelY">--</span>
                <span class="axis-unit">m/s²</span>
              </span>
            </div>

            <div class="axis-row">
              <span class="axis-label">Z</span>
              <span class="axis-value">
                <span id="accelZ">--</span>
                <span class="axis-unit">m/s²</span>
              </span>
            </div>
          </div>


          <div>
            <div class="motion-group-title">
              Gyroscope
            </div>

            <div class="axis-row">
              <span class="axis-label">X</span>
              <span class="axis-value">
                <span id="gyroX">--</span>
                <span class="axis-unit">rad/s</span>
              </span>
            </div>

            <div class="axis-row">
              <span class="axis-label">Y</span>
              <span class="axis-value">
                <span id="gyroY">--</span>
                <span class="axis-unit">rad/s</span>
              </span>
            </div>

            <div class="axis-row">
              <span class="axis-label">Z</span>
              <span class="axis-value">
                <span id="gyroZ">--</span>
                <span class="axis-unit">rad/s</span>
              </span>
            </div>
          </div>

        </div>

      </div>


      <div class="panel orientation-panel">

        <div class="panel-title">
          Orientation
        </div>

        <div class="orientation-values">

          <div class="axis-row">
            <span class="axis-label">I</span>
            <span
              id="quatI"
              class="axis-value">--</span>
          </div>

          <div class="axis-row">
            <span class="axis-label">J</span>
            <span
              id="quatJ"
              class="axis-value">--</span>
          </div>

          <div class="axis-row">
            <span class="axis-label">K</span>
            <span
              id="quatK"
              class="axis-value">--</span>
          </div>

          <div class="axis-row">
            <span class="axis-label">R</span>
            <span
              id="quatReal"
              class="axis-value">--</span>
          </div>

        </div>

      </div>


      <div class="panel hall-panel">

        <div class="panel-title">
          Hall
        </div>

        <div class="hall-center">

          <div
            id="hallLamp"
            class="hall-lamp clear">
          </div>

          <div
            id="hall"
            class="hall-text">
            CLEAR
          </div>

        </div>

        <div class="hall-note">
          DRV5032
        </div>

      </div>


      <div class="panel fan-panel">

        <div class="panel-title">
          Fan Control
        </div>


        <div class="fan-row">

          <div class="fan-name">
            INTAKE
          </div>

          <div class="fan-levels">

            <button id="fanIntake0"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('intake',0)">
              OFF
            </button>

            <button id="fanIntake25"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('intake',25)">
              25
            </button>

            <button id="fanIntake50"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('intake',50)">
              50
            </button>

            <button id="fanIntake75"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('intake',75)">
              75
            </button>

            <button id="fanIntake100"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('intake',100)">
              100
            </button>

          </div>

          <div
            id="intakeActual"
            class="fan-actual">
            0%
          </div>

        </div>


        <div class="fan-row">

          <div class="fan-name">
            EXHAUST
          </div>

          <div class="fan-levels">

            <button id="fanExhaust0"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('exhaust',0)">
              OFF
            </button>

            <button id="fanExhaust25"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('exhaust',25)">
              25
            </button>

            <button id="fanExhaust50"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('exhaust',50)">
              50
            </button>

            <button id="fanExhaust75"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('exhaust',75)">
              75
            </button>

            <button id="fanExhaust100"
                    class="fan-button"
                    type="button"
                    onclick="sendFanLevel('exhaust',100)">
              100
            </button>

          </div>

          <div
            id="exhaustActual"
            class="fan-actual">
            0%
          </div>

        </div>


        <div class="fan-bottom">

          <div
            id="controlStatus"
            class="control-status">
            Ready
          </div>

          <button
            id="fanAllOff"
            class="all-off"
            type="button"
            onclick="sendFans(0,0)">
            ALL OFF
          </button>

        </div>

      </div>

    </section>


    <!-- ==========================================
         Always-visible history
         ========================================== -->

    <section class="panel history-panel">

      <div class="history-toolbar">

        <div class="panel-title">
          Sensor History
        </div>

        <div class="history-ranges">

          <button id="range1"
                  class="range-button"
                  type="button"
                  onclick="setHistoryRange(1)">
            1m
          </button>

          <button id="range5"
                  class="range-button active"
                  type="button"
                  onclick="setHistoryRange(5)">
            5m
          </button>

          <button id="range10"
                  class="range-button"
                  type="button"
                  onclick="setHistoryRange(10)">
            10m
          </button>

          <button id="range20"
                  class="range-button"
                  type="button"
                  onclick="setHistoryRange(20)">
            20m
          </button>

          <button id="range30"
                  class="range-button"
                  type="button"
                  onclick="setHistoryRange(30)">
            30m
          </button>

        </div>

      </div>


      <div class="mini-chart-grid">


        <div
          id="chartCardTemperature"
          class="mini-chart">

          <div class="mini-chart-header">
            <div class="mini-chart-title">
              Temperature
            </div>

            <div class="mini-legend">
              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#58a6ff"></span>
                Compute
              </span>

              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#ff9b66"></span>
                Exhaust
              </span>

              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#63d69d"></span>
                Ambient
              </span>
            </div>
          </div>

          <canvas
            id="chartTemperature"
            class="mini-canvas">
          </canvas>

        </div>


        <div
          id="chartCardHumidity"
          class="mini-chart">

          <div class="mini-chart-header">
            <div class="mini-chart-title">
              Humidity
            </div>
          </div>

          <canvas
            id="chartHumidity"
            class="mini-canvas">
          </canvas>

        </div>


        <div
          id="chartCardPressure"
          class="mini-chart">

          <div class="mini-chart-header">
            <div class="mini-chart-title">
              Pressure
            </div>
          </div>

          <canvas
            id="chartPressure"
            class="mini-canvas">
          </canvas>

        </div>


        <div
          id="chartCardAcceleration"
          class="mini-chart">

          <div class="mini-chart-header">
            <div class="mini-chart-title">
              Acceleration
            </div>

            <div class="mini-legend">
              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#58a6ff"></span>X
              </span>

              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#ff9b66"></span>Y
              </span>

              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#63d69d"></span>Z
              </span>
            </div>
          </div>

          <canvas
            id="chartAcceleration"
            class="mini-canvas">
          </canvas>

        </div>


        <div
          id="chartCardGyro"
          class="mini-chart">

          <div class="mini-chart-header">
            <div class="mini-chart-title">
              Gyroscope
            </div>

            <div class="mini-legend">
              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#58a6ff"></span>X
              </span>

              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#ff9b66"></span>Y
              </span>

              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#63d69d"></span>Z
              </span>
            </div>
          </div>

          <canvas
            id="chartGyro"
            class="mini-canvas">
          </canvas>

        </div>


        <div
          id="chartCardOrientation"
          class="mini-chart">

          <div class="mini-chart-header">
            <div class="mini-chart-title">
              Orientation
            </div>

            <div class="mini-legend">
              <span>I</span>
              <span>J</span>
              <span>K</span>
              <span>R</span>
            </div>
          </div>

          <canvas
            id="chartOrientation"
            class="mini-canvas">
          </canvas>

        </div>


        <div
          id="chartCardHall"
          class="mini-chart">

          <div class="mini-chart-header">
            <div class="mini-chart-title">
              Hall
            </div>

            <div class="mini-legend">
              0 Clear · 1 Magnet
            </div>
          </div>

          <canvas
            id="chartHall"
            class="mini-canvas">
          </canvas>

        </div>


        <div
          id="chartCardFans"
          class="mini-chart">

          <div class="mini-chart-header">
            <div class="mini-chart-title">
              Fan Output
            </div>

            <div class="mini-legend">
              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#58a6ff"></span>
                Intake
              </span>

              <span class="mini-legend-item">
                <span class="mini-swatch"
                      style="background:#ff9b66"></span>
                Exhaust
              </span>
            </div>
          </div>

          <canvas
            id="chartFans"
            class="mini-canvas">
          </canvas>

        </div>


      </div>

    </section>

  </div>


  <script>

    const STALE_SECONDS = 8;

    let latestFanState = {
      intake_pct: 0,
      exhaust_pct: 0
    };

    let telemetryReady = false;
    let controlBusy = false;
    let pendingFanCommand = null;

    let historyMetric = "temperature";
    let historyMinutes = 5;
    let latestHistory = [];


    const SERIES_COLORS = [
      "#58a6ff",
      "#ff9b66",
      "#63d69d",
      "#c084fc"
    ];


    const HISTORY = {

      temperature: {
        title: "Temperature History",
        unit: "°C",

        series: [
          {
            label: "Compute",
            value: s =>
              s.temperatures?.compute_c
          },
          {
            label: "Exhaust",
            value: s =>
              s.temperatures?.exhaust_c
          },
          {
            label: "Ambient",
            value: s =>
              s.environment?.temperature_c
          }
        ]
      },


      humidity: {
        title: "Humidity History",
        unit: "%",

        series: [
          {
            label: "Humidity",
            value: s =>
              s.environment?.humidity_pct
          }
        ]
      },


      pressure: {
        title: "Pressure History",
        unit: "hPa",

        series: [
          {
            label: "Pressure",
            value: s =>
              s.environment?.pressure_hpa
          }
        ]
      },


      acceleration: {
        title: "Acceleration History",
        unit: "m/s²",

        series: [
          {
            label: "X",
            value: s => s.motion?.accel_x
          },
          {
            label: "Y",
            value: s => s.motion?.accel_y
          },
          {
            label: "Z",
            value: s => s.motion?.accel_z
          }
        ]
      },


      gyro: {
        title: "Gyroscope History",
        unit: "",

        series: [
          {
            label: "X",
            value: s => s.motion?.gyro_x
          },
          {
            label: "Y",
            value: s => s.motion?.gyro_y
          },
          {
            label: "Z",
            value: s => s.motion?.gyro_z
          }
        ]
      },


      orientation: {
        title: "Orientation History",
        unit: "",

        series: [
          {
            label: "I",
            value: s => s.motion?.quat_i
          },
          {
            label: "J",
            value: s => s.motion?.quat_j
          },
          {
            label: "K",
            value: s => s.motion?.quat_k
          },
          {
            label: "Real",
            value: s => s.motion?.quat_real
          }
        ]
      },


      hall: {
        title: "Hall Sensor History",
        unit: "",
        yMin: -0.08,
        yMax: 1.08,

        series: [
          {
            label: "0 Clear · 1 Magnet",
            step: true,

            value: s =>
              s.hall?.active
                ? 1
                : 0
          }
        ]
      },


      fans: {
        title: "Fan Output History",
        unit: "%",
        yMin: 0,
        yMax: 100,

        series: [
          {
            label: "Intake",
            step: true,

            value: s =>
              s.fans?.intake_pct
          },
          {
            label: "Exhaust",
            step: true,

            value: s =>
              s.fans?.exhaust_pct
          }
        ]
      }

    };


    function el(id) {
      return document.getElementById(id);
    }


    function finite(value) {
      return (
        typeof value === "number" &&
        Number.isFinite(value)
      );
    }


    function show(value, digits = 2) {

      if (!finite(value)) {
        return "--";
      }

      return value.toFixed(digits);
    }


    function clamp(value, min, max) {
      return Math.max(
        min,
        Math.min(max, value)
      );
    }

    function ensureGaugeScale(
      arcId,
      min,
      max
    ) {

      const arc =
        el(arcId);

      const svg =
        arc.closest("svg");


      if (
        svg.querySelector(
          ".gauge-scale"
        )
      ) {
        return;
      }


      const ns =
        "http://www.w3.org/2000/svg";

      const group =
        document.createElementNS(
          ns,
          "g"
        );

      group.setAttribute(
        "class",
        "gauge-scale"
      );


      /*
       * Gauge geometry:
       *
       * center = 60,60
       * arc radius = 50
       *
       * Five marks at:
       * 180°, 135°, 90°, 45°, 0°
       */

      for (let i = 0; i <= 4; i++) {

        const fraction =
          i / 4;

        const angle =
          Math.PI -
          fraction * Math.PI;


        const outerRadius = 48;
        const innerRadius = 42;

        const labelRadius =
          arcId === "pressureArc"
            ? 39
            : 36;


        const x1 =
          60 +
          Math.cos(angle) *
          outerRadius;

        const y1 =
          60 -
          Math.sin(angle) *
          outerRadius;


        const x2 =
          60 +
          Math.cos(angle) *
          innerRadius;

        const y2 =
          60 -
          Math.sin(angle) *
          innerRadius;


        const tx =
          60 +
          Math.cos(angle) *
          labelRadius;

        const ty =
          60 -
          Math.sin(angle) *
          labelRadius;


        const tick =
          document.createElementNS(
            ns,
            "line"
          );

        tick.setAttribute(
          "x1",
          x1
        );

        tick.setAttribute(
          "y1",
          y1
        );

        tick.setAttribute(
          "x2",
          x2
        );

        tick.setAttribute(
          "y2",
          y2
        );

        tick.setAttribute(
          "class",
          i === 2
            ? "gauge-scale-tick major"
            : "gauge-scale-tick"
        );


        const label =
          document.createElementNS(
            ns,
            "text"
          );


        const scaleValue =
          min +
          fraction *
          (max - min);


        label.textContent =
          Number.isInteger(scaleValue)
            ? scaleValue
            : scaleValue.toFixed(1);


        label.setAttribute(
          "x",
          tx
        );

        label.setAttribute(
          "y",
          ty
        );

        label.setAttribute(
          "class",
          arcId === "pressureArc"
            ? "gauge-scale-label pressure"
            : "gauge-scale-label"
        );

        label.setAttribute(
          "text-anchor",
          "middle"
        );

        label.setAttribute(
          "dominant-baseline",
          "middle"
        );


        group.appendChild(tick);
        group.appendChild(label);
      }


      /*
       * Insert the scale before the live value arc
       * so the active arc remains visually dominant.
       */

      svg.insertBefore(
        group,
        arc
      );
    }


    function setGauge(
      valueId,
      arcId,
      value,
      min,
      max,
      digits
    ) {

      ensureGaugeScale(
        arcId,
        min,
        max
      );


      el(valueId).textContent =
        show(value, digits);


      let pct = 0;


      if (finite(value)) {

        pct =
          100 *
          (
            clamp(
              value,
              min,
              max
            ) -
            min
          ) /
          (
            max -
            min
          );

      }


      el(arcId).style.strokeDasharray =
        pct.toFixed(1) +
        " 100";
    }


    function setStatus(data) {

      const badge =
        el("statusBadge");

      const age =
        data.age_s;

      let text = "LIVE";
      let cls = "live";


      if (data.status === "waiting") {

        text = "WAITING";
        cls = "waiting";

      }
      else if (
        age === undefined ||
        age === null ||
        age > STALE_SECONDS
      ) {

        text = "STALE";
        cls = "stale";

      }
      else if (data.status !== "ok") {

        text = "DEGRADED";
        cls = "degraded";

      }


      badge.textContent = text;
      badge.className =
        "status-badge " + cls;
    }


    function setErrors(errors) {

      const strip =
        el("errorStrip");

      if (!errors || errors.length === 0) {

        strip.style.display = "none";
        strip.textContent = "";
        return;
      }

      strip.textContent =
        errors.join(" · ");

      strip.style.display = "block";
    }


    function refreshFanControls() {

      const buttons =
        document.querySelectorAll(
          ".fan-button"
        );

      for (const button of buttons) {

        button.disabled =
          controlBusy ||
          !telemetryReady;
      }


      el("fanAllOff").disabled =
        controlBusy;
    }


    function updateFanDisplay(data) {

      for (const button of
        document.querySelectorAll(
          ".fan-button"
        )) {

        button.classList.remove(
          "actual"
        );
      }

      el("fanAllOff").classList.remove(
        "actual"
      );


      const intake =
        Number(
          data.fans?.intake_pct ?? 0
        );

      const exhaust =
        Number(
          data.fans?.exhaust_pct ?? 0
        );


      latestFanState = {
        intake_pct: intake,
        exhaust_pct: exhaust
      };


      el("intakeActual").textContent =
        intake + "%";

      el("exhaustActual").textContent =
        exhaust + "%";


      const intakeButton =
        el("fanIntake" + intake);

      const exhaustButton =
        el("fanExhaust" + exhaust);


      if (intakeButton) {
        intakeButton.classList.add(
          "actual"
        );
      }

      if (exhaustButton) {
        exhaustButton.classList.add(
          "actual"
        );
      }


      if (intake === 0 && exhaust === 0) {

        el("fanAllOff").classList.add(
          "actual"
        );
      }


      if (pendingFanCommand !== null) {

        if (
          intake ===
            pendingFanCommand.intake_pct &&
          exhaust ===
            pendingFanCommand.exhaust_pct
        ) {

          el("controlStatus").textContent =
            "Confirmed by Pico";

          el("controlStatus").className =
            "control-status confirmed";

          pendingFanCommand = null;
        }
      }


      refreshFanControls();
    }


    function updateDisplay(d) {

      setStatus(d);


      setGauge(
        "compute",
        "computeArc",
        d.temperatures?.compute_c,
        0,
        100,
        1
      );

      setGauge(
        "exhaust",
        "exhaustArc",
        d.temperatures?.exhaust_c,
        0,
        60,
        1
      );

      setGauge(
        "ambient",
        "ambientArc",
        d.environment?.temperature_c,
        0,
        60,
        1
      );

      setGauge(
        "humidity",
        "humidityArc",
        d.environment?.humidity_pct,
        0,
        100,
        1
      );

      setGauge(
        "pressure",
        "pressureArc",
        d.environment?.pressure_hpa,
        950,
        1050,
        1
      );


      el("accelX").textContent =
        show(d.motion?.accel_x, 3);

      el("accelY").textContent =
        show(d.motion?.accel_y, 3);

      el("accelZ").textContent =
        show(d.motion?.accel_z, 3);


      el("gyroX").textContent =
        show(d.motion?.gyro_x, 3);

      el("gyroY").textContent =
        show(d.motion?.gyro_y, 3);

      el("gyroZ").textContent =
        show(d.motion?.gyro_z, 3);


      el("quatI").textContent =
        show(d.motion?.quat_i, 3);

      el("quatJ").textContent =
        show(d.motion?.quat_j, 3);

      el("quatK").textContent =
        show(d.motion?.quat_k, 3);

      el("quatReal").textContent =
        show(d.motion?.quat_real, 3);


      const hallActive =
        d.hall?.active === true;

      el("hall").textContent =
        hallActive
          ? "MAGNET"
          : "CLEAR";

      el("hallLamp").className =
        "hall-lamp " +
        (
          hallActive
            ? "magnet"
            : "clear"
        );


      el("firmware").textContent =
        d.firmware ?? "--";

      el("seq").textContent =
        d.seq ?? "--";


      el("uptime").textContent =
        finite(d.uptime_s)
          ? d.uptime_s.toFixed(0) + "s"
          : "--";

      el("age").textContent =
        finite(d.age_s)
          ? d.age_s.toFixed(1) + "s"
          : "--";


      telemetryReady =
        d.status !== "waiting" &&
        finite(d.age_s) &&
        d.age_s <= STALE_SECONDS;


      updateFanDisplay(d);
      setErrors(d.errors);
    }


    function setSystemLamp(
      elementId,
      state,
      age,
      error
    ) {

      const lamp =
        el(elementId);


      if (state === true) {

        lamp.className =
          "system-dot ok";

      }
      else if (state === false) {

        lamp.className =
          "system-dot bad";

      }
      else {

        lamp.className =
          "system-dot unknown";

      }


      let title = "";


      if (age !== null &&
          age !== undefined &&
          finite(age)) {

        title +=
          "Age: " +
          age.toFixed(1) +
          "s";
      }


      if (error) {

        if (title) {
          title += " · ";
        }

        title += error;
      }


      lamp.parentElement.title =
        title || "Status unavailable";
    }


    async function updateSystem() {

      try {

        const response =
          await fetch(
            "/api/system",
            {
              cache: "no-store"
            }
          );


        if (!response.ok) {

          throw new Error(
            "HTTP " +
            response.status
          );
        }


        const data =
          await response.json();


        setSystemLamp(
          "systemPico",
          data.pico?.ok,
          data.pico?.age_s,
          null
        );


        setSystemLamp(
          "systemBridge",
          data.bridge?.ok,
          data.bridge?.age_s,
          null
        );


        setSystemLamp(
          "systemCluster",
          data.cluster?.ok,
          data.cluster?.check_age_s,
          data.cluster?.error
        );

      }
      catch (err) {

        setSystemLamp(
          "systemPico",
          null,
          null,
          null
        );

        setSystemLamp(
          "systemBridge",
          null,
          null,
          null
        );

        setSystemLamp(
          "systemCluster",
          null,
          null,
          err.message
        );
      }
    }


    async function updateTelemetry() {

      try {

        const response =
          await fetch(
            "/api/telemetry",
            {
              cache: "no-store"
            }
          );


        if (!response.ok) {
          throw new Error(
            "HTTP " + response.status
          );
        }


        const data =
          await response.json();

        updateDisplay(data);

      }
      catch (err) {

        telemetryReady = false;
        refreshFanControls();

        el("statusBadge").textContent =
          "OFFLINE";

        el("statusBadge").className =
          "status-badge stale";
      }
    }


    async function sendFanLevel(
      fan,
      level
    ) {

      let intake =
        latestFanState.intake_pct;

      let exhaust =
        latestFanState.exhaust_pct;


      if (fan === "intake") {

        intake = level;

      }
      else if (fan === "exhaust") {

        exhaust = level;

      }
      else {

        return;

      }


      await sendFans(
        intake,
        exhaust
      );
    }


    async function sendFans(
      intake,
      exhaust
    ) {

      controlBusy = true;
      refreshFanControls();

      el("controlStatus").textContent =
        "Sending...";

      el("controlStatus").className =
        "control-status";


      try {

        const response =
          await fetch(
            "/api/control",
            {
              method: "POST",

              headers: {
                "Content-Type":
                  "application/json"
              },

              body: JSON.stringify({
                intake_pct: intake,
                exhaust_pct: exhaust
              })
            }
          );


        if (!response.ok) {

          const text =
            await response.text();

          throw new Error(
            "HTTP " +
            response.status +
            (text ? ": " + text : "")
          );
        }


        await response.json();


        pendingFanCommand = {
          intake_pct: intake,
          exhaust_pct: exhaust
        };


        el("controlStatus").textContent =
          "Waiting for Pico...";

      }
      catch (err) {

        pendingFanCommand = null;

        el("controlStatus").textContent =
          "Control failed";

        el("controlStatus").className =
          "control-status error";
      }
      finally {

        controlBusy = false;
        refreshFanControls();
      }
    }


    function selectHistory(metric) {

      const ids = {
        temperature:
          "chartCardTemperature",

        humidity:
          "chartCardHumidity",

        pressure:
          "chartCardPressure",

        acceleration:
          "chartCardAcceleration",

        gyro:
          "chartCardGyro",

        orientation:
          "chartCardOrientation",

        hall:
          "chartCardHall",

        fans:
          "chartCardFans"
      };


      for (const id of
        Object.values(ids)) {

        const card = el(id);

        if (card) {
          card.classList.remove(
            "selected"
          );
        }
      }


      const target =
        el(ids[metric]);

      if (target) {

        target.classList.add(
          "selected"
        );

        setTimeout(
          () => target.classList.remove(
            "selected"
          ),
          1200
        );
      }
    }


    function setHistoryRange(minutes) {

      historyMinutes = minutes;

      for (const value of [
        1,
        5,
        10,
        20,
        30
      ]) {

        el(
          "range" + value
        ).classList.toggle(
          "active",
          value === minutes
        );
      }

      updateHistory();
    }


    function formatTime(timestamp) {

      const date =
        new Date(timestamp * 1000);

      return date.toLocaleTimeString(
        [],
        {
          hour: "2-digit",
          minute: "2-digit"
        }
      );
    }


    function drawMiniChart(
      canvasId,
      configKey
    ) {

      const canvas =
        el(canvasId);

      const config =
        HISTORY[configKey];

      const samples =
        latestHistory;


      const rect =
        canvas.getBoundingClientRect();

      const ratio =
        window.devicePixelRatio || 1;

      const width =
        Math.max(
          240,
          rect.width
        );

      const height =
        Math.max(
          60,
          rect.height
        );


      canvas.width =
        Math.round(
          width * ratio
        );

      canvas.height =
        Math.round(
          height * ratio
        );


      const ctx =
        canvas.getContext("2d");


      ctx.setTransform(
        ratio,
        0,
        0,
        ratio,
        0,
        0
      );


      ctx.clearRect(
        0,
        0,
        width,
        height
      );


      const left = 39;
      const right = 5;
      const top = 5;
      const bottom = 16;

      const plotWidth =
        width - left - right;

      const plotHeight =
        height - top - bottom;


      if (!samples ||
          samples.length < 2) {

        ctx.fillStyle = "#667681";
        ctx.font = "10px system-ui";
        ctx.textAlign = "center";

        ctx.fillText(
          "Collecting...",
          width / 2,
          height / 2
        );

        return;
      }


      const startTime =
        samples[0].received_at;

      const endTime =
        samples[
          samples.length - 1
        ].received_at;


      let values = [];


      for (const series of
        config.series) {

        for (const sample of samples) {

          const value =
            series.value(sample);

          if (finite(value)) {
            values.push(value);
          }
        }
      }


      if (values.length === 0) {
        return;
      }


      let minValue =
        config.yMin !== undefined
          ? config.yMin
          : Math.min(...values);

      let maxValue =
        config.yMax !== undefined
          ? config.yMax
          : Math.max(...values);


      if (minValue === maxValue) {

        minValue -= 1;
        maxValue += 1;

      }
      else if (
        config.yMin === undefined &&
        config.yMax === undefined
      ) {

        const pad =
          (maxValue - minValue) *
          0.10;

        minValue -= pad;
        maxValue += pad;
      }


      function xFor(time) {

        if (endTime === startTime) {
          return left;
        }

        return left +
          (
            (time - startTime) /
            (endTime - startTime)
          ) *
          plotWidth;
      }


      function yFor(value) {

        return top +
          (
            1 -
            (
              (value - minValue) /
              (maxValue - minValue)
            )
          ) *
          plotHeight;
      }


      ctx.font = "9px system-ui";


      for (let i = 0; i <= 2; i++) {

        const fraction =
          i / 2;

        const y =
          top +
          fraction *
          plotHeight;

        const value =
          maxValue -
          fraction *
          (maxValue - minValue);


        ctx.strokeStyle = "#263039";
        ctx.lineWidth = 1;

        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(
          left + plotWidth,
          y
        );
        ctx.stroke();


        ctx.fillStyle = "#687783";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";

        ctx.fillText(
          value.toFixed(1),
          left - 4,
          y
        );
      }


      ctx.fillStyle = "#687783";
      ctx.textBaseline = "top";

      ctx.textAlign = "left";

      ctx.fillText(
        formatTime(startTime),
        left,
        top + plotHeight + 4
      );


      ctx.textAlign = "right";

      ctx.fillText(
        formatTime(endTime),
        left + plotWidth,
        top + plotHeight + 4
      );


      config.series.forEach(
        (series, index) => {

          ctx.strokeStyle =
            SERIES_COLORS[
              index %
              SERIES_COLORS.length
            ];

          ctx.lineWidth = 1.5;
          ctx.lineJoin = "round";
          ctx.lineCap = "round";

          ctx.beginPath();


          let drawing = false;
          let previousY = null;


          for (const sample of samples) {

            const value =
              series.value(sample);

            const time =
              sample.received_at;


            if (
              !finite(value) ||
              !finite(time)
            ) {

              drawing = false;
              previousY = null;
              continue;
            }


            const x =
              xFor(time);

            const y =
              yFor(value);


            if (!drawing) {

              ctx.moveTo(x, y);
              drawing = true;

            }
            else if (series.step) {

              ctx.lineTo(
                x,
                previousY
              );

              ctx.lineTo(
                x,
                y
              );

            }
            else {

              ctx.lineTo(x, y);

            }


            previousY = y;
          }


          ctx.stroke();
        }
      );
    }


    function drawAllHistory() {

      drawMiniChart(
        "chartTemperature",
        "temperature"
      );

      drawMiniChart(
        "chartHumidity",
        "humidity"
      );

      drawMiniChart(
        "chartPressure",
        "pressure"
      );

      drawMiniChart(
        "chartAcceleration",
        "acceleration"
      );

      drawMiniChart(
        "chartGyro",
        "gyro"
      );

      drawMiniChart(
        "chartOrientation",
        "orientation"
      );

      drawMiniChart(
        "chartHall",
        "hall"
      );

      drawMiniChart(
        "chartFans",
        "fans"
      );
    }


    async function updateHistory() {

      try {

        const response =
          await fetch(
            "/api/history?minutes=" +
            historyMinutes,
            {
              cache: "no-store"
            }
          );


        if (!response.ok) {
          throw new Error(
            "HTTP " + response.status
          );
        }


        const data =
          await response.json();


        latestHistory =
          data.samples || [];


        drawAllHistory();

      }
      catch (err) {

        console.error(
          "History unavailable:",
          err
        );
      }
    }


    window.addEventListener(
      "resize",
      drawAllHistory
    );


    updateTelemetry();
    updateSystem();
    updateHistory();

    setInterval(
      updateTelemetry,
      1000
    );


    setInterval(
      updateSystem,
      2000
    );

    setInterval(
      updateHistory,
      3000
    );

  </script>

</body>
</html>
"""



def check_cluster_ready():

    global cluster_check_at
    global cluster_ready
    global cluster_error

    now = time.time()

    # Cache the Kubernetes result briefly so browser
    # polling does not hammer the API server.
    if (
        cluster_check_at > 0
        and now - cluster_check_at
            < CLUSTER_CACHE_SECONDS
    ):

        return (
            cluster_ready,
            cluster_error,
            now - cluster_check_at
        )


    cluster_check_at = now


    url = (
        "https://kubernetes.default.svc/"
        "readyz"
    )

    token_path = (
        "/var/run/secrets/kubernetes.io/"
        "serviceaccount/token"
    )

    ca_path = (
        "/var/run/secrets/kubernetes.io/"
        "serviceaccount/ca.crt"
    )


    try:

        with open(token_path) as f:
            token = f.read().strip()


        context = ssl.create_default_context(
            cafile=ca_path
        )


        request = urllib.request.Request(
            url,
            headers={
                "Authorization":
                    "Bearer " + token
            }
        )


        with urllib.request.urlopen(
            request,
            context=context,
            timeout=2
        ) as response:

            body = (
                response.read()
                .decode()
                .strip()
            )


            cluster_ready = (
                response.status == 200
                and body == "ok"
            )


            if cluster_ready:

                cluster_error = None

            else:

                cluster_error = (
                    "unexpected readiness response"
                )


    except Exception as exc:

        cluster_ready = False
        cluster_error = str(exc)


    return (
        cluster_ready,
        cluster_error,
        0.0
    )


class Handler(BaseHTTPRequestHandler):

    def send_body(
        self,
        status,
        content_type,
        body
    ):
        self.send_response(status)

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()
        self.wfile.write(body)


    def do_GET(self):

        global latest
        global received_at
        global latest_control
        global history
        global bridge_heartbeat_at

        parsed = urlparse(
            self.path
        )

        path = parsed.path


        if path == "/api/history":

            try:

                params = parse_qs(
                    parsed.query
                )

                raw_minutes = params.get(
                    "minutes",
                    ["5"]
                )[0]

                minutes = int(
                    raw_minutes
                )

                allowed = (
                    1,
                    5,
                    10,
                    20,
                    30
                )

                if minutes not in allowed:
                    raise ValueError(
                        "minutes must be one of "
                        "1, 5, 10, 20, 30"
                    )


                cutoff = (
                    time.time()
                    -
                    minutes * 60
                )


                samples = [
                    sample
                    for sample in history
                    if sample["received_at"] >= cutoff
                ]


                response = {
                    "minutes": minutes,
                    "count": len(samples),
                    "samples": samples
                }


                body = json.dumps(
                    response
                ).encode()


                self.send_body(
                    200,
                    "application/json",
                    body
                )

            except Exception as exc:

                body = json.dumps({
                    "error": str(exc)
                }).encode()

                self.send_body(
                    400,
                    "application/json",
                    body
                )

            return


        if path == "/api/system":

            now = time.time()


            pico_age = (
                None
                if received_at is None
                else now - received_at
            )


            bridge_age = (
                None
                if bridge_heartbeat_at is None
                else now - bridge_heartbeat_at
            )


            pico_ok = (
                pico_age is not None
                and pico_age
                    <= PICO_FRESH_SECONDS
            )


            bridge_ok = (
                bridge_age is not None
                and bridge_age
                    <= BRIDGE_FRESH_SECONDS
            )


            (
                cluster_ok,
                cluster_problem,
                cluster_age
            ) = check_cluster_ready()


            response = {

                "pico": {
                    "ok": pico_ok,

                    "age_s": (
                        None
                        if pico_age is None
                        else round(
                            pico_age,
                            1
                        )
                    )
                },

                "bridge": {
                    "ok": bridge_ok,

                    "age_s": (
                        None
                        if bridge_age is None
                        else round(
                            bridge_age,
                            1
                        )
                    )
                },

                "cluster": {
                    "ok": cluster_ok,

                    "check_age_s": round(
                        cluster_age,
                        1
                    ),

                    "error": cluster_problem
                }
            }


            body = json.dumps(
                response
            ).encode()


            self.send_body(
                200,
                "application/json",
                body
            )

            return


        if path == "/api/control":

            body = json.dumps(
                latest_control
            ).encode()

            self.send_body(
                200,
                "application/json",
                body
            )

            return


        if path == "/api/telemetry":

            data = (
                dict(latest)
                if latest is not None
                else empty_telemetry()
            )

            if latest is not None:

                data["received_at"] = (
                    received_at
                )

                data["age_s"] = round(
                    time.time() -
                    received_at,
                    1
                )

            body = json.dumps(
                data
            ).encode()

            self.send_body(
                200,
                "application/json",
                body
            )


        elif path == "/healthz":

            self.send_body(
                200,
                "text/plain",
                b"ok\n"
            )


        else:

            self.send_body(
                200,
                "text/html",
                PAGE.encode()
            )


    def do_POST(self):

        global latest
        global received_at
        global latest_control
        global history
        global bridge_heartbeat_at


        # ------------------------------------------
        # Fan-control endpoint
        # ------------------------------------------

        if self.path == "/api/control":

            try:

                length = int(
                    self.headers.get(
                        "Content-Length",
                        "0"
                    )
                )

                if length <= 0 or length > 4096:
                    raise ValueError(
                        "invalid content length"
                    )

                body = self.rfile.read(
                    length
                )

                data = json.loads(
                    body
                )

                intake_pct = data.get(
                    "intake_pct"
                )

                exhaust_pct = data.get(
                    "exhaust_pct"
                )

                valid_levels = (
                    0,
                    25,
                    50,
                    75,
                    100
                )

                if type(intake_pct) is not int:
                    raise ValueError(
                        "intake_pct must be an integer"
                    )

                if type(exhaust_pct) is not int:
                    raise ValueError(
                        "exhaust_pct must be an integer"
                    )

                if intake_pct not in valid_levels:
                    raise ValueError(
                        "intake_pct must be one of "
                        "0, 25, 50, 75, 100"
                    )

                if exhaust_pct not in valid_levels:
                    raise ValueError(
                        "exhaust_pct must be one of "
                        "0, 25, 50, 75, 100"
                    )

                latest_control = {
                    "id": int(
                        time.time() * 1000
                    ),
                    "command": "fans",
                    "intake_pct": intake_pct,
                    "exhaust_pct": exhaust_pct
                }

                response = json.dumps(
                    latest_control
                ).encode()

                self.send_body(
                    202,
                    "application/json",
                    response
                )

            except Exception as exc:

                response = json.dumps({
                    "error": str(exc)
                }).encode()

                self.send_body(
                    400,
                    "application/json",
                    response
                )

            return


        # ------------------------------------------
        # Telemetry endpoint
        # ------------------------------------------

        # ------------------------------------------
        # Bridge heartbeat endpoint
        # ------------------------------------------

        if self.path == "/api/bridge-heartbeat":

            bridge_heartbeat_at = time.time()

            self.send_response(204)
            self.end_headers()

            return


        if self.path != "/api/telemetry":

            self.send_body(
                404,
                "text/plain",
                b"not found\n"
            )

            return


        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            if length <= 0 or length > 65536:

                raise ValueError(
                    "invalid content length"
                )


            body = self.rfile.read(
                length
            )

            data = json.loads(
                body
            )


            if data.get("schema") != \
                    "sensortrain.telemetry.v1":

                raise ValueError(
                    "unsupported telemetry schema"
                )


            latest = data
            received_at = time.time()

            history_sample = dict(
                data
            )

            history_sample[
                "received_at"
            ] = received_at

            history.append(
                history_sample
            )


            self.send_body(
                204,
                "text/plain",
                b""
            )


        except Exception as exc:

            body = json.dumps({
                "error": str(exc)
            }).encode()


            self.send_body(
                400,
                "application/json",
                body
            )


    def log_message(
        self,
        format,
        *args
    ):
        pass


HTTPServer(
    ("0.0.0.0", 8080),
    Handler
).serve_forever()

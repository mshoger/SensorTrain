#!/usr/bin/python3

import json
import os
import select
import threading
import termios
import time
import tty
import urllib.request


DEVICE = os.environ.get(
    "PICO_DEVICE",
    "/dev/sensortrain-pico"
)

TELEMETRY_URL = os.environ.get(
    "TELEMETRY_URL",
    "http://127.0.0.1:8080/api/telemetry"
)

CONTROL_URL = os.environ.get(
    "CONTROL_URL",
    "http://127.0.0.1:8080/api/control"
)

HEARTBEAT_URL = (
    TELEMETRY_URL.rsplit("/", 1)[0]
    + "/bridge-heartbeat"
)

HEARTBEAT_SECONDS = 2.0

CONTROL_POLL_SECONDS = 0.5
ACK_RETRY_SECONDS = 6.0



def post_bridge_heartbeat():

    request = urllib.request.Request(
        HEARTBEAT_URL,
        data=b"",
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=2
    ) as response:

        if response.status != 204:

            raise RuntimeError(
                "unexpected heartbeat "
                "HTTP status {}".format(
                    response.status
                )
            )


def heartbeat_loop():

    last_error = None
    first_success = True

    while True:

        try:

            post_bridge_heartbeat()

            if first_success:

                print(
                    "Bridge heartbeat established",
                    flush=True
                )

                first_success = False

            elif last_error is not None:

                print(
                    "Bridge heartbeat recovered",
                    flush=True
                )

            last_error = None


        except Exception as exc:

            message = str(exc)

            # Avoid filling journald with the same
            # failure every two seconds.
            if message != last_error:

                print(
                    "Bridge heartbeat failed: {}".format(
                        message
                    ),
                    flush=True
                )

            last_error = message
            first_success = False


        time.sleep(
            HEARTBEAT_SECONDS
        )


def post_telemetry(record):

    body = json.dumps(
        record,
        separators=(",", ":")
    ).encode("utf-8")

    request = urllib.request.Request(
        TELEMETRY_URL,
        data=body,
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=3
    ) as response:

        if response.status != 204:
            raise RuntimeError(
                "unexpected telemetry HTTP status {}".format(
                    response.status
                )
            )


def get_control():

    request = urllib.request.Request(
        CONTROL_URL,
        headers={
            "Cache-Control": "no-store"
        },
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=2
    ) as response:

        if response.status != 200:
            raise RuntimeError(
                "unexpected control HTTP status {}".format(
                    response.status
                )
            )

        return json.loads(
            response.read().decode("utf-8")
        )


def send_control(fd, control):

    if control.get("command") != "fans":
        return False

    control_id = control.get("id")

    if not control_id:
        return False


    intake_pct = control.get(
        "intake_pct"
    )

    exhaust_pct = control.get(
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
        return False

    if type(exhaust_pct) is not int:
        return False

    if intake_pct not in valid_levels:
        return False

    if exhaust_pct not in valid_levels:
        return False


    command = {
        "command": "fans",
        "id": control_id,
        "intake_pct": intake_pct,
        "exhaust_pct": exhaust_pct
    }


    wire = (
        json.dumps(
            command,
            separators=(",", ":")
        )
        +
        chr(10)
    ).encode("utf-8")


    os.write(
        fd,
        wire
    )

    termios.tcdrain(
        fd
    )


    print(
        "Control sent: "
        "id={} intake={}% exhaust={}%".format(
            control_id,
            intake_pct,
            exhaust_pct
        ),
        flush=True
    )

    return True


def run_serial(fd):

    tty.setraw(fd)
    termios.tcflush(fd, termios.TCIFLUSH)

    buffer = b""
    telemetry_count = 0

    last_sent_id = None
    last_acked_id = None

    pending_id = None
    pending_since = 0.0

    next_control_poll = 0.0

    print(
        "Pico connected: {}".format(DEVICE),
        flush=True
    )

    while True:

        now = time.monotonic()

        # ------------------------------------------
        # Poll MicroShift for desired control state.
        # ------------------------------------------

        if now >= next_control_poll:

            next_control_poll = (
                now + CONTROL_POLL_SECONDS
            )

            try:
                control = get_control()

                control_id = control.get("id")

                should_send = (
                    control_id
                    and control_id != last_acked_id
                    and (
                        control_id != last_sent_id
                        or (
                            pending_id == control_id
                            and
                            now - pending_since >=
                            ACK_RETRY_SECONDS
                        )
                    )
                )

                if should_send:

                    if send_control(
                        fd,
                        control
                    ):
                        last_sent_id = control_id
                        pending_id = control_id
                        pending_since = now

            except Exception as exc:

                print(
                    "Control poll failed: {}".format(
                        exc
                    ),
                    flush=True
                )


        # ------------------------------------------
        # Read Pico serial data.
        # ------------------------------------------

        timeout = max(
            0.0,
            min(
                0.25,
                next_control_poll -
                time.monotonic()
            )
        )

        readable, _, _ = select.select(
            [fd],
            [],
            [],
            timeout
        )

        if not readable:
            continue

        chunk = os.read(
            fd,
            4096
        )

        if not chunk:
            raise OSError(
                "Pico disconnected"
            )

        buffer += chunk


        while b"\n" in buffer:

            line, buffer = buffer.split(
                b"\n",
                1
            )

            line = line.strip()

            if not line.startswith(b"{"):
                continue


            try:

                record = json.loads(
                    line.decode(
                        "utf-8",
                        errors="strict"
                    )
                )

            except Exception:
                continue


            schema = record.get(
                "schema"
            )


            # --------------------------------------
            # Normal telemetry
            # --------------------------------------

            if schema == \
                    "sensortrain.telemetry.v1":

                try:

                    post_telemetry(
                        record
                    )

                    telemetry_count += 1

                    if (
                        telemetry_count == 1
                        or
                        telemetry_count % 25 == 0
                    ):

                        print(
                            "Telemetry forwarded: seq={}".format(
                                record.get("seq")
                            ),
                            flush=True
                        )

                except Exception as exc:

                    print(
                        "Telemetry POST failed: {}".format(
                            exc
                        ),
                        flush=True
                    )


            # --------------------------------------
            # Pico control acknowledgement
            # --------------------------------------

            elif schema == \
                    "sensortrain.control.ack.v1":

                command = record.get(
                    "command",
                    {}
                )

                ack_id = command.get(
                    "id"
                )

                if (
                    record.get("status") == "ok"
                    and
                    ack_id is not None
                ):

                    last_acked_id = ack_id

                    if pending_id == ack_id:
                        pending_id = None

                    fans = record.get(
                        "fans",
                        {}
                    )

                    print(
                        "Control ACK: "
                        "id={} intake={}%% exhaust={}%%".format(
                            ack_id,
                            fans.get("intake_pct"),
                            fans.get("exhaust_pct")
                        ),
                        flush=True
                    )

                else:

                    print(
                        "Control ACK error: {}".format(
                            record
                        ),
                        flush=True
                    )


def main():

    print(
        "SensorTrain bidirectional bridge starting",
        flush=True
    )

    print(
        "Telemetry destination: {}".format(
            TELEMETRY_URL
        ),
        flush=True
    )

    print(
        "Control source: {}".format(
            CONTROL_URL
        ),
        flush=True
    )


    print(
        "Heartbeat destination: {}".format(
            HEARTBEAT_URL
        ),
        flush=True
    )

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        name="sensortrain-heartbeat",
        daemon=True
    )

    heartbeat_thread.start()


    while True:

        fd = None

        try:

            fd = os.open(
                DEVICE,
                os.O_RDWR |
                os.O_NOCTTY
            )

            run_serial(
                fd
            )

        except Exception as exc:

            print(
                "Pico unavailable: {}".format(
                    exc
                ),
                flush=True
            )

            time.sleep(2)

        finally:

            if fd is not None:

                try:
                    os.close(fd)
                except Exception:
                    pass


if __name__ == "__main__":
    main()

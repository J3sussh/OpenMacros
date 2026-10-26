# HID++ protocol as implemented by this project

This document specifies the subset of the Logitech HID++ protocol that the project speaks, exactly as
`src/openmacros/hidpp/` and `src/openmacros/daemon/` implement it. It is not a complete description of HID++.
Features, functions and flags the code does not use are left out or marked "not used".

Conventions: all multi-byte integers are big-endian unless stated otherwise. "Params" are the bytes
that follow the 4-byte report header. Byte offsets inside a payload are zero-based.

Contents

1. [Transport](#1-transport)
2. [Message format](#2-message-format)
3. [Errors](#3-errors)
4. [Request handling](#4-request-handling)
5. [Feature discovery](#5-feature-discovery)
6. [Features](#6-features)
7. [Receivers](#7-receivers)
8. [Control IDs (CIDs)](#8-control-ids-cids)
9. [Example device: M720 Triathlon](#9-example-device-m720-triathlon)
10. [Gesture engine](#10-gesture-engine)
11. [Sources and clean-room policy](#11-sources-and-clean-room-policy)

---

## 1. Transport

The project talks to devices through Linux `hidraw` nodes (`/dev/hidrawN`), opened read/write and
non-blocking.

**Node selection.** A node is a candidate when all of these hold:

- its sysfs `uevent` reports vendor ID `0x046D`;
- its HID report descriptor declares Report ID `0x11`.

Bluetooth LE devices expose only the long report. Receivers also expose the short one. Other report
IDs on the same node (for example standard mouse reports with ID `0x02`) are ignored when read.

The `HID_ID` field of the `uevent` gives the bus (`0x0005` = Bluetooth) and the product ID. Receivers
are recognised by product ID (section 7).

**Report IDs and sizes.**

| Report ID | Name       | Total size | Max params |
|-----------|------------|-----------:|-----------:|
| `0x10`    | short      | 7 bytes    | 3          |
| `0x11`    | long       | 20 bytes   | 16         |
| `0x12`    | very long  | 64 bytes   | 60         |

Reports are written zero-padded to their full size. A read returns at most 64 bytes. A report that
is shorter than the size its ID requires is rejected.

**Report choice.** The encoder picks the smallest report that fits the params and is not smaller than
a minimum:

- HID++ 2.0 requests use long (`0x11`) as the minimum. All receivers and devices accept it.
- HID++ 1.0 register requests use short (`0x10`) as the minimum.

**Device index** (byte 1 of every report):

| Value   | Meaning |
|---------|---------|
| `0xFF`  | The receiver itself (register access), or a device reached directly (Bluetooth, USB). |
| `1`-`6` | Slot of a paired device behind a receiver. |

## 2. Message format

Every report has a 4-byte header followed by params:

```
byte 0   report ID (0x10 / 0x11 / 0x12)
byte 1   device index
byte 2   feature index (HID++ 2.0)   |  sub ID (HID++ 1.0)
byte 3   function << 4 | software ID |  register address (HID++ 1.0)
byte 4.. params
```

### HID++ 2.0

- **Feature index** is the slot of a feature in the device's own table (section 5). It differs between
  devices. Index `0` is always the Root feature.
- **Function** is the high nibble of byte 3 (0-15).
- **Software ID** is the low nibble of byte 3. The host picks a value 1-15 per request and cycles
  through them. The device echoes it in the response, which lets the host match replies to requests.
  Value `0` is reserved for device-initiated notifications.

A response has the same device index, feature index, function and software ID as its request. An
event (notification) has software ID `0`, and its function nibble is the event number.

### HID++ 1.0 (receiver registers and notifications)

| Sub ID | Meaning |
|--------|---------|
| `0x80` | SET_REGISTER (short) |
| `0x81` | GET_REGISTER (short response) |
| `0x83` | GET_LONG_REGISTER (long response) |
| `0x8F` | Error report |
| `0x40`-`0x7F` | Receiver notifications (for example `0x40` disconnect, `0x41` connect) |

Byte 3 is the register address. The response to a register request echoes sub ID and address.

## 3. Errors

### HID++ 1.0 error report (`byte 2 = 0x8F`)

```
byte 2   0x8F
byte 3   sub ID of the failed request
byte 4   address of the failed request
byte 5   error code
```

| Code   | Meaning |
|-------:|---------|
| `0x00` | success |
| `0x01` | invalid sub ID |
| `0x02` | invalid address |
| `0x03` | invalid value |
| `0x04` | connect fail |
| `0x05` | too many devices |
| `0x06` | already exists |
| `0x07` | busy |
| `0x08` | unknown device |
| `0x09` | resource error |
| `0x0A` | request unavailable |
| `0x0B` | invalid param value |
| `0x0C` | wrong PIN code |

A device that only speaks HID++ 1.0 answers any HID++ 2.0 request with this error. In that case
byte 3 holds the feature index and byte 4 holds `function << 4 | swId` of the request. The client
matches the error on those values. The Root ping (section 5) treats code `0x01` as "device is
HID++ 1.0".

### HID++ 2.0 error report (`byte 2 = 0xFF`)

```
byte 2   0xFF
byte 3   feature index of the failed request
byte 4   function << 4 | software ID of the failed request
byte 5   error code
```

| Code   | Meaning |
|-------:|---------|
| `0x00` | no error |
| `0x01` | unknown |
| `0x02` | invalid argument |
| `0x03` | out of range |
| `0x04` | hardware error |
| `0x05` | internal error |
| `0x06` | invalid feature index |
| `0x07` | invalid function ID |
| `0x08` | busy |
| `0x09` | unsupported |

## 4. Request handling

Behaviour of `hidpp/channel.py`:

1. **Send.** A request takes the next software ID and is written as one report.
2. **Wait.** The client reads reports until one of these arrives or the deadline passes
   (default 1.5 s; the daemon uses 1.0 s; receiver probes use 0.3-0.5 s):
   - a matching response: returns its params;
   - a matching error report (1.0 or 2.0 form): raises an error;
   - a timeout: raises `HidppTimeout`.
3. **Busy retry.** On HID++ 2.0 error `0x08` (busy) the request is resent with a new software ID, up
   to 4 attempts in total, sleeping 50 ms x attempt between them. Other errors are not retried.
4. **Interleaved traffic.** While waiting, any report that is not the reply is classified:
   - notification: a report with sub ID `0x40`-`0x7F`, or a HID++ 2.0 report with feature index
     below `0x40` and software ID `0`. It is queued and dispatched after the request finishes;
   - error report for another request, or a late reply (software ID not 0): dropped.
5. **Idle reading.** When no request is in flight, the daemon reads whatever is available and
   dispatches notifications to handlers.

Fire-and-forget: Change Host (section 6.4) is sent as a normal request, but a timeout or a closed
node is treated as success, because the device usually drops the link.

## 5. Feature discovery

### 5.1 Root (`0x0000`, always at index 0)

| Fn | Name | Request params | Response params |
|---:|------|----------------|-----------------|
| 0 | getFeature | `[featureId (2)]` | `[index, type, version]`; `index = 0` means "not supported" |
| 1 | ping | `[0x00, 0x00, 0xA5]` | `[protocolMajor, protocolMinor, ...]` |

Ping is used to learn the HID++ version and to check that a device behind a receiver is online. If
the device answers with HID++ 1.0 error `0x01`, the protocol is recorded as `1.0` and the device is
not otherwise used.

### 5.2 FeatureSet (`0x0001`)

| Fn | Name | Request params | Response params |
|---:|------|----------------|-----------------|
| 0 | getCount | none | `[count]` (number of features excluding Root) |
| 1 | getFeatureId | `[index]` | `[featureId (2), type, version]` |

Layout note: the code reads the feature ID from bytes 0-1 and the version from byte 3 of the response.
Byte 2 holds the feature type flags and is not used.

### 5.3 Cache

Each device object keeps three maps: feature ID to index, index to feature ID, and feature ID to
version. Lookup order:

1. Cached index.
2. If the device has already been fully enumerated through FeatureSet, an unknown feature ID is
   "absent" (negative cache). No request is sent.
3. Otherwise, Root `getFeature` is called and the result cached.

On connection the daemon calls `ping`, then enumerates the whole FeatureSet, so every later lookup is
served from the cache. The cache is rebuilt on every reconnection (a device may have changed its
feature table after a firmware update or host switch).

### 5.4 Notification dispatch

An incoming report with software ID `0` is mapped from feature index to feature ID through the cache
and delivered as `(featureId, event number, params)` to the device's listener. Reports with software
ID other than 0, or with an unknown index, are ignored.

## 6. Features

For each feature below, "fn" is the function number placed in the high nibble of byte 3. Request and
response payloads are params only.

### 6.1 `0x0003` Device Information (unit ID, model IDs)

Used function: `fn 0` getDeviceInfo, no request params.

Response layout (as read by the project):

| Offset | Size | Field |
|-------:|-----:|-------|
| 0 | 1 | entity count (not used) |
| 1 | 4 | unit ID |
| 5 | 2 | supported transports bitmask (not used) |
| 7 | 2 x 3 | model IDs, one per transport slot; zero entries are skipped |

The device ID shown to users is `logi:` plus the unit ID as upper-case hex. If the feature is
missing, or the unit ID is all zeros, the project falls back to the receiver serial plus the slot
index, or to the product ID plus the slot index.

Model IDs are used behind a receiver when the wireless product ID (WPID) is unknown. The order of
the transport slots is not guaranteed; the code uses the last non-zero ID when more than one is
present.

### 6.2 `0x0005` Device Name and Type

| Fn | Name | Request | Response |
|---:|------|---------|----------|
| 0 | getNameLength | none | `[length]` |
| 1 | getName | `[offset]` | up to 16 bytes of name starting at `offset` |
| 2 | getType | none | `[type]` |

The name is read in chunks until `length` bytes have been collected, or until a chunk is all zeros.
It is cut at the first NUL and decoded as UTF-8 (invalid bytes replaced).

Types: `0` keyboard, `1` remote, `2` numpad, `3` mouse, `4` touchpad, `5` trackball, `6` presenter,
`7` receiver. The project maps `0`, `3`, `4`, `5` to `keyboard`, `mouse`, `touchpad`, `trackball`;
everything else becomes `other`.

### 6.3 `0x1000` Battery Status and `0x1004` Unified Battery

The project prefers `0x1004` when present, then `0x1000`.

**`0x1000`**, `fn 0` getBatteryLevelStatus (no params). Response:

| Offset | Field |
|-------:|-------|
| 0 | discharge level, percent |
| 1 | next level (not used) |
| 2 | status |

The level is reported as approximate because some devices give coarse steps.

**`0x1004`**, `fn 1` getStatus (no params). Response:

| Offset | Field |
|-------:|-------|
| 0 | state of charge, percent |
| 1 | level bitmask (not used) |
| 2 | status |

**Status byte** (same mapping for both): `0` discharging; `1`, `2`, `4` charging; `3` full;
`5`, `6`, `7` error (`7` only in `0x1004`); any other value is "unknown".

**Event.** Event `0` of either feature carries the same payload as the corresponding getter. The
daemon parses it and refreshes the stored battery state.

### 6.4 `0x1814` Change Host and `0x1815` Hosts Info (Easy-Switch)

**`0x1814`**

| Fn | Name | Request | Response |
|---:|------|---------|----------|
| 0 | getHostInfo | none | `[hostCount, currentHost]` (0-based) |
| 1 | setCurrentHost | `[host]` (0-based) | usually none; the device drops the link |

**`0x1815`** (only used as a fallback for the count and for names)

| Fn | Name | Request | Response (as read) |
|---:|------|---------|--------------------|
| 0 | getHostsInfo | none | `[flags, hostCount, currentHost]` |
| 1 | getHostInfo | `[hostIndex]` | byte 5 = host name length |
| 4 | getHostName | `[hostIndex, offset]` | `[hostIndex, offset, chunk...]` |

Names are best effort. They are read in chunks up to the reported length. If any request fails, or
all names come back empty, the project reports no names (the M720 firmware returns empty names).

### 6.5 `0x1B04` Reprogrammable Keys and Mouse Buttons

Functions used:

| Fn | Name | Request | Response |
|---:|------|---------|----------|
| 0 | getCount | none | `[count]` |
| 1 | getCidInfo | `[index]` | 9 bytes, see below |
| 2 | getCidReporting | `[cid (2)]` | `[cid (2), flags1, remap (2), flags2]` |
| 3 | setCidReporting | 6 bytes, see below | echo (ignored) |
| 5 | resetAllReporting | none | none (ignored) |

**getCidInfo response** (index is 0-based, `0 <= index < count`):

| Offset | Size | Field |
|-------:|-----:|-------|
| 0 | 2 | CID |
| 2 | 2 | task ID (TID): the default function of the control |
| 4 | 1 | flags1 |
| 5 | 1 | position (not used) |
| 6 | 1 | group (not used) |
| 7 | 1 | group mask (not used) |
| 8 | 1 | flags2 |

Bits the project reads:

| Field | Bit | Meaning |
|-------|----:|---------|
| flags1 | `0x10` | reprogrammable |
| flags1 | `0x20` | divertable |
| flags1 | `0x40` | divertable persistently |
| flags1 | `0x80` | virtual (no physical button; hidden from the UI) |
| flags2 | `0x01` | can report raw XY movement while held |

A control counts as "divertable" when bit `0x20` or `0x40` is set. The other flag bits are not used.

The project exposes `raw_xy` to the UI only for controls that advertise flags2 `0x01` **and** are in
the gesture-button set (`0xC3`, `0xD0`). The M720 advertises raw XY on every divertable control, so
the second condition matters.

**getCidReporting response.** Bytes 0-1 CID; byte 2 flags1 using the same bit layout as the request
below (only the value bits are read: divert `0x01`, persist `0x04`, rawXY `0x10`); bytes 3-4 remap CID
(`0` = none); byte 5 flags2 (not used).

**setCidReporting request (6 bytes).**

| Offset | Size | Field |
|-------:|-----:|-------|
| 0 | 2 | CID |
| 2 | 1 | flags1 |
| 3 | 2 | remap CID (`0` = no remap) |
| 5 | 1 | flags2 (always sent as `0x00`) |

flags1 uses a "value bit + valid bit" scheme. A value bit is applied only if its valid bit is also
set, so one call can change one property and leave the others alone.

| Property | Value bit | Valid bit |
|----------|----------:|----------:|
| divert | `0x01` | `0x02` |
| persist | `0x04` | `0x08` |
| rawXY | `0x10` | `0x20` |

Encoding rule used by the code, for each property: if the caller gives no value, both bits are 0; if
it gives a value, the valid bit is set and the value bit is set only for "true".

| Intent | flags1 |
|--------|-------:|
| divert + rawXY (gesture button) | `0x33` |
| divert only (button on a rawXY-capable control; also clears rawXY) | `0x23` |
| divert only (control not rawXY-capable) | `0x03` |
| no divert (default behaviour), rawXY-capable control | `0x22` |
| no divert, control not rawXY-capable | `0x02` |

Example: divert the M720 thumb button (CID `0x00D0`) and receive raw movement while it is held:

```
fn 3 params: 00 D0  33  00 00  00
             cid    f1  remap  f2
```

With `remap != 0` and divert off, the device itself acts as if the remapped button was pressed
(firmware-level remap, no host involvement).

**resetAllReporting (fn 5)** clears every divert and remap. The daemon calls it right after reading
the controls on each connection, to clear state left by a previous daemon process; it calls it again
when the user resets a device. Diverts are not persistent across a device reset or power cycle; the
daemon re-applies its configuration on every reconnect.

**Events.**

| Event | Name | Params |
|------:|------|--------|
| 0 | divertedButtonsEvent | up to four CIDs (u16 each, 8 bytes), zero-padded. The list is the set of diverted controls currently held. An empty list means everything was released. |
| 1 | divertedRawXYEvent | `dx` (int16), `dy` (int16) since the previous event, while a rawXY-enabled control is held. |

Event 0 is a state snapshot, not a press/release pair. The host keeps the previous set and derives
presses (new CIDs) and releases (missing CIDs) by diffing. Other event numbers are ignored.

### 6.6 `0x2121` Hi-Res Wheel

| Fn | Name | Request | Response |
|---:|------|---------|----------|
| 1 | getWheelMode | none | `[mode]` |
| 2 | setWheelMode | `[mode]` | echo (ignored) |

Mode bits: `0x01` target (HID++ report instead of HID; preserved, never changed), `0x02` high
resolution, `0x04` inverted.

To change one setting the project reads the mode, flips only that bit, and writes the whole byte
back.

### 6.7 `0x2201` Adjustable DPI

All calls use sensor index `0`.

| Fn | Name | Request | Response |
|---:|------|---------|----------|
| 1 | getSensorDpiList | `[0x00]` | `[sensor, list...]` |
| 2 | getSensorDpi | `[0x00]` | `[sensor, dpi (2), defaultDpi (2)]` |
| 3 | setSensorDpi | `[0x00, dpi (2)]` | echo (ignored) |

The list after the sensor byte is a sequence of u16 values ending at the first `0x0000`. A value
below `0xE000` is a DPI value. A value `0xE000 + step` is a range marker: it is followed by the upper
bound, and means "every `step` DPI from the previous value up to that bound, inclusive". The decoder
caps the expanded list at 512 entries.

The project reads only the current DPI (bytes 1-2 of the `getSensorDpi` response).

### 6.8 `0x2205` Pointer Speed

| Fn | Name | Request | Response |
|---:|------|---------|----------|
| 0 | getPointerSpeed | none | `[speed (2)]` |
| 1 | setPointerSpeed | `[speed (2)]` | echo (ignored) |

The valid range the project offers is `0x002E` to `0x01FF` (46-511). It is a fixed constant in the
code, not read from the device.

### 6.9 `0x2110` SmartShift and `0x2111` SmartShift with torque

The project prefers `0x2111` when present. The two variants differ only in function numbers.

| Feature | Get fn | Set fn |
|---------|-------:|-------:|
| `0x2110` | 0 | 1 |
| `0x2111` | 1 | 2 |

Get response: `[mode, autoDisengage, ...]`. Set request: `[mode, autoDisengage, 0x00]`.

- `mode`: `1` free-spin, `2` ratchet.
- `autoDisengage`: `1`-`254` is the wheel speed at which the ratchet releases into free-spin
  (SmartShift threshold); `255` means "never release" (SmartShift off).

The project's "enabled" state is `mode == 2 and autoDisengage < 255`. On write it always sends mode
`2`, with the threshold clamped to `1`-`254` when enabled, or `255` when disabled.

## 7. Receivers

### 7.1 Recognised receiver product IDs (vendor `0x046D`)

| PID | Family |
|-----|--------|
| `c52b`, `c532` | Unifying |
| `c52f`, `c534` | Nano |
| `c539`, `c53a`, `c53d`, `c545`, `c54d` | Lightspeed |
| `c548` | Bolt |

A receiver supports up to 6 paired devices (slots 1-6). Receivers speak HID++ 1.0 for their own
management, and relay HID++ 2.0 traffic to the devices by device index.

### 7.2 Registers used

All register requests use device index `0xFF`.

| Register | Access | Params | Purpose |
|---------:|--------|--------|---------|
| `0x00` | GET `0x81`, SET `0x80` | `00 09 00` | Notification flags: enable wireless-device notifications and mark the host software as present. The client reads first and writes only if the value differs. |
| `0x02` | SET `0x80` | `02 00 00` | Connection state: make the receiver resend a connect notification (`0x41`) for every paired device that is on. |
| `0xB5` | GET_LONG `0x83` | `03` | Receiver serial: bytes 1-4 of the response, upper-case hex. |
| `0xB5` | GET_LONG `0x83` | `0x20 + slot - 1` | Pairing info of one slot (Unifying and Nano only, see below). |

**Pairing info (`0xB5`, sub-register `0x20 + n - 1`).** From the response params: bytes 3-4 are the
device's wireless product ID (big-endian), byte 6 is the device type. A WPID of `0` means "empty
slot". Bolt receivers use a different layout; the project does not parse it and returns no pairing
info for them (the WPID then comes from the connect notification, or from `0x0003` model IDs).

### 7.3 Enumeration at start-up

1. Read register `0x00` and write it if it is not `00 09 00`.
2. Read the receiver serial (register `0xB5`, sub `0x03`).
3. For each slot 1-6, send a Root ping with a 0.3 s timeout. Slots that answer are online. For
   each, read pairing info to learn the WPID.
4. Each online slot becomes a device and goes through normal feature discovery.

### 7.4 Connection notifications

Sub ID `0x40` and `0x41` reports, with the device index set to the slot:

| Sub ID | Meaning | Params |
|-------:|---------|--------|
| `0x40` | device disconnected (or powered off, or moved to another host) | not used |
| `0x41` | device connected or link changed | see below |

For `0x41`:

| Offset | Meaning |
|-------:|---------|
| 0 | bit `0x40` set: link **not** established (device away); otherwise connected. The low nibble is kept as a device-kind value; the project does not act on it. |
| 1-2 | wireless PID, **little-endian** (byte 2 is the high byte) |

Note that the WPID is little-endian here but big-endian in the `0xB5` pairing response.

On a connect notification for a known slot, the daemon marks it online and re-reads everything (it
may have changed host in between). For an unknown slot it builds a new device, taking the WPID from
the notification (or from `0xB5` if it is zero) and runs full discovery. On a disconnect
notification the slot is marked offline but kept in the manager.

## 8. Control IDs (CIDs)

CIDs name physical controls in feature `0x1B04`. This table lists the CIDs the project knows. Names
are the project's own wording; any CID not listed is shown as `Button 0xNN`.

| CID | Name used by the project | Re-emitted as (default action) |
|----:|--------------------------|--------------------------------|
| `0x50` | Left button | `BTN_LEFT` |
| `0x51` | Right button | `BTN_RIGHT` |
| `0x52` | Wheel button | `BTN_MIDDLE` |
| `0x53` | Back | `BTN_SIDE` |
| `0x54` | Scroll-down button | none |
| `0x55` | Scroll-up button | none |
| `0x56` | Forward | `BTN_EXTRA` |
| `0x57` | Extra side button | none |
| `0x5B` | Wheel tilt left | `REL_HWHEEL -1` |
| `0x5D` | Wheel tilt right | `REL_HWHEEL +1` |
| `0xC3` | Gesture button | none |
| `0xC4` | Wheel-mode switch | none |
| `0xC5` | Wheel-mode switch (alternate) | none |
| `0xD0` | Gesture button | none |
| `0xFD` | DPI change | none |

"Re-emitted as" is what the daemon generates through `uinput` when a diverted control is configured
with the `default` action, so the button keeps working while the host listens to it. Tilt buttons have
no key code and become one horizontal-wheel step per press. Controls with no entry are not
re-emitted.

CIDs `0xC3` and `0xD0` are the gesture-button set: the only controls for which the project enables
raw XY.

## 9. Example device: M720 Triathlon

| Mode | Interface | Product ID |
|------|-----------|-----------:|
| Bluetooth LE | hidraw direct, device index `0xFF` | `b015` |
| Unifying receiver (`046d:c52b`) | hidraw of the receiver, device index = slot | `405e` |

Observed with the author's hardware:

- Easy-Switch hosts: 3. Hi-res wheel: yes (`0x2121`). Battery: `0x1000`, not Unified.
- The firmware returns empty Easy-Switch host names, so the UI shows none.
- `0x1B04` advertises raw XY on every divertable control.

Controls exposed by the project's `m720` layout:

| CID | Hex | Button |
|----:|----:|--------|
| 82 | `0x52` | Wheel click |
| 83 | `0x53` | Back |
| 86 | `0x56` | Forward |
| 91 | `0x5B` | Wheel tilt left |
| 93 | `0x5D` | Wheel tilt right |
| 208 | `0xD0` | Thumb button (gestures) |

## 10. Gesture engine

Gestures are computed on the host from `0x1B04` events. The firmware only reports raw movement.

**Arming.** When an action of type `gestures` is assigned to a control, the daemon sends
`setCidReporting` with divert and rawXY (flags1 `0x33`, section 6.5).

**Per press** (`daemon/gestures.py`):

1. Event 0 lists the CID for the first time: start a gesture. `dx = dy = 0`, not yet fired.
2. Each event 1 adds its signed `dx`, `dy` to the running totals.
3. After each update, with `ax = |dx|`, `ay = |dy|`:
   - **Horizontal**: if `ax >= threshold` and `atan2(ay, ax) <= 30 degrees`, fire `right` when
     `dx > 0`, else `left`.
   - **Vertical**: else if `ay >= threshold` and `atan2(ax, ay) <= 30 degrees`, fire `down` when
     `dy > 0`, else `up` (positive `dy` is downward).
4. At most one direction fires per press. After it fires, further movement is ignored.
5. Event 0 no longer lists the CID (release): if nothing fired, the gesture is a `click`; otherwise
   nothing more happens.

**Parameters.**

| Parameter | Value |
|-----------|-------|
| Threshold | per-assignment, in raw device counts; default `50`; values below 1 are raised to 1 |
| Angle tolerance | 30 degrees on either side of the horizontal or vertical axis |
| Diagonals | no gesture fires; the movement keeps accumulating until it enters an axis cone |

**Actions.** Each of `click`, `up`, `down`, `left`, `right` has its own configured action.
`disabled` and missing actions do nothing. `default` is honoured only for `click`: it re-emits the
physical button as described in section 8 (a direction with `default` does nothing).

**Re-emission of the default button.** A diverted control whose action is `default` is passed through
by generating the matching `uinput` key (or wheel step). Controls whose action is `disabled` or
`remap` produce no host-side event. `remap` is performed by the device firmware (section 6.5).

**State changes.** If the assignments change while a control is held and its configuration is the
same, the running gesture keeps its totals. If the configuration changed, the control is
treated as released, and a release event is generated for the old action if it was a held
non-gesture action (not `disabled`, `remap` or `gestures`).

## 11. Sources and clean-room policy

This specification is based on:

- the HID++ 2.0 documentation published by Logitech;
- free and open-source projects that document or implement the protocol: Solaar, libratbag (its
  HID++ driver) and logiops;
- black-box tests on the author's own hardware (sending requests, reading responses, and observing
  the device's behaviour).

No code, image or text from Logitech software is present in this repository. Contributors must not
add any. Protocol details contributed for new devices should come from public documentation or from
your own packet captures on your own hardware (see `docs/DEVICES.md`).

Logitech, Unifying, Bolt, Easy-Switch and other names are trademarks of their owners and appear only
to indicate compatibility. This project is not affiliated with Logitech.

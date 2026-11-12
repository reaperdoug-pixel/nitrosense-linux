# NitroSense for Linux (English)

> The main README is in Portuguese: [README.md](../README.md). This is its English version.

<!-- Keep in sync with ../README.md: same sections, tables and code blocks. The Portuguese file is the reference. -->

**A monitoring and control dashboard for Acer Nitro laptops on Linux: fan control with an
automatic curve, SSD and battery health, history, power, throttling detection, alerts and
more.**

This is a fork of [napejoon/nitrosense-linux](https://github.com/napejoon/nitrosense-linux), a
port of Acer NitroSense 3.01 for Windows. The fork keeps the part that makes it work, a root
service that talks to the Acer firmware with the same WMI commands Windows NitroSense sends,
and replaces the Windows-style window with a new dashboard. It was developed on an **Acer Nitro
ANV15-51** (Intel + GeForce RTX 3050) running Linux Mint 22.
The interface is in **Brazilian Portuguese**.

> 🇧🇷 [Português (idioma principal)](../README.md) · 🇹🇭 [คู่มือภาษาไทย](README.th.md) (upstream's, for the original window)

---

## Contents

- [Highlights](#highlights)
- [Supported hardware](#supported-hardware)
- [Requirements](#requirements)
- [Installation](#installation)
- [Using the dashboard](#using-the-dashboard)
- [Alerts](#alerts)
- [Safety](#safety)
- [How it works](#how-it-works)
- [Files and configuration](#files-and-configuration)
- [Service API](#service-api)
- [Firmware interface reference](#firmware-interface-reference)
- [Security model](#security-model)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [Development](#development)
- [Origin and credits](#origin-and-credits)
- [Limitations](#limitations)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Highlights

| Tab | What it shows or does |
|---|---|
| **Início** (Home) | CPU and GPU temperature gauges, fan RPM, power in watts, GPU load, the performance state (normal, or held back by heat or power) with the CPU clock, scenario summary, SSD and battery health at a glance. |
| **Cenário** (Scenario) | Power plans for AC and battery, and fan control: **Auto**, **Max**, **Custom** (CPU and GPU sliders), **Curve** (a draggable temperature/speed graph, one for both fans or one per fan, with safety rules) and **CoolBoost**. |
| **Discos** (Disks) | NVMe health from SMART: wear, spare capacity, power-on hours, data written and read, unsafe shutdowns, media errors, temperature, file-system use, plain-language advice. |
| **Bateria** (Battery) | Health (full-charge capacity against the original), cycles, charge, power draw, time left, history charts, a switch to **limit charging to about 80 %** and the battery **calibration**. |
| **Monitoramento** (Monitoring) | Live 12-minute charts of CPU and GPU temperature and load, with watts and clocks. |
| **Processos** (Processes) | The heaviest programs by CPU, memory and GPU, and what keeps the discrete GPU awake. |
| **Histórico** (History) | 1 hour to 30 days of temperatures, CPU and GPU power, CPU frequency with throttled periods marked, battery charge and draw, and the SSD wear trend. |

Behind the window:

- **A service that never sleeps.** `nitrosensed` runs as root, re-applies your settings at
  boot, after resume and when you plug or unplug the charger, and records the history around
  the clock, even with the window closed.
- **Alerts with the window closed.** `nitrosense-watch` sends desktop notifications for high
  temperatures, a stopped fan, SSD or battery trouble, and sustained thermal throttling of the CPU or the GPU.
- **Never wakes the discrete GPU.** NVML and `nvidia-smi` are used only while the GPU is
  already awake, so monitoring does not stop it from saving power.
- **The NitroSense key** on the keyboard opens the dashboard.

---

## Supported hardware

| Status | Models |
|---|---|
| ✅ Developed and tested | **Acer Nitro ANV15-51** (Intel, GeForce RTX 3050 6 GB), Linux Mint 22.3, kernel 7.0 |
| ✅ Tested by the upstream project | **Acer Nitro AN515-44** (Ryzen 4000 + GTX 1650 Ti, BIOS V1.04), Ubuntu 24.04 |
| 🟡 Should work (same WMI interface, `MachineType=1`), untested | AN515-43, AN515-45, AN515-51s, AN515-54, AN515-55, AN515-56, AN515-57, AN517-41, AN517-51, AN517-52, AN517-53, AN517-54, AN715-41, AN715-51, AN715-52, N9500-A, T9300 |
| ❌ Not supported (different NitroSense) | `MachineType=2` models with operation modes (AN515-46/47/58, AN517-42/43/55, Nitro ANX), and older `MachineType=0` models |

What depends on the hardware:

| Feature | Needs |
|---|---|
| Fan control, sensors, CoolBoost, power plans | The Acer WMI methods (`AcerGamingFunction`) and the `acpi_call` module |
| CPU power in watts | Intel RAPL counters under `/sys/class/powercap` (Intel; AMD untested) |
| CPU throttling detection | The kernel's `thermal_throttle` counters and thermal cooling devices (Intel) |
| Disk health | An **NVMe** drive (SATA drives are not covered) |
| GPU power, clock and slowdown reasons | An NVIDIA GPU with the proprietary driver (`libnvidia-ml`) |
| GPU per-program use | `nvidia-smi` |
| Battery charge limit | The Acer battery health WMI interface (GUID `79772EC5-…`); the switch appears only when the firmware reports it |
| Keyboard lighting | The service supports it, but the dashboard has no lighting panel (see [Limitations](#limitations)); the ANV15-51 firmware rejects the backlight command anyway |

Per-model options (fan count, lighting type, visible settings) come from `Feature.ini` and
`HW_Support.ini`. The repository bundles the ANV15-51 files in `data/models/`; for another
model the installer can take them from the Windows NitroSense package (`Plugs/<model>/`).

On an untested model, start with the read-only probe, `sudo python3 -I tools/probe.py`, and
check that the temperatures and RPM it prints look right.

---

## Requirements

- An Acer Nitro laptop (see above) running **Linux Mint 22 / Ubuntu 24.04** or another
  Debian-based distribution with **GTK 4.10+** and Python 3.10+.
- Installed automatically: `python3-gi`, `python3-gi-cairo`, `python3-cairo`,
  `gir1.2-gtk-4.0`, `acpi-call-dkms`.
- **Secure Boot**: `acpi_call` is an out-of-tree module built by DKMS. With Secure Boot on,
  DKMS signs it with your Machine Owner Key (MOK). If you have never enrolled one, the system asks
  for a password during installation and for *Enroll MOK* on the next boot (blue screen).
- Optional: the NVIDIA driver for the GPU readings. If `thermald` or Intel DPTF is running, its
  limits show up in the throttling detection through the thermal cooling devices.
- Optional: the **NitroSense package for Windows** of your model. It is only used for the
  per-model `.ini` files of models not bundled here and for the app icon; the dashboard itself
  uses no Acer artwork.

---

## Installation

```bash
git clone https://github.com/reaperdoug-pixel/nitrosense-linux.git
cd nitrosense-linux
sudo ./install.sh                       # bundled model files and icon
# or, to read the model files and icon from your own NitroSense package:
sudo ./install.sh "/path/to/Nitro Sense_Acer_3.01.3056_W10x64_A"
```

What the installer does:

1. Checks that the machine is an Acer and installs the dependencies.
2. Loads `acpi_call` and sets it to load at boot.
3. Runs a **read-only hardware probe** (getter methods only). If the values look wrong it
   stops and installs nothing else.
4. Copies the program to `/opt/nitrosense`.
5. With a package: extracts its artwork into `/usr/share/nitrosense/assets` (nothing from it is
   executed). Without one: uses the project's own icon.
6. Copies the model files (`data/models/<model>/` or the package's `Plugs/<model>/`) to
   `/etc/nitrosense/model/`.
7. Lets the user who ran `sudo` talk to the service.
8. Installs the menu entry, the icon, the `nitrosense` command and the **alert watcher**
   autostart (`/etc/xdg/autostart/nitrosense-watch.desktop`).
9. Sets up the **NitroSense key** (see [below](#the-nitrosense-key)).
10. Enables and starts the `nitrosensed` service.

Then open **NitroSense** from the application menu, or run `nitrosense`. The watcher starts
with your next login; to start it now run `setsid /opt/nitrosense/bin/nitrosense-watch &`.

**Updating**: `git pull` and run the installer again. Your settings and the history in
`/var/lib/nitrosense` are kept. After an update restart the watcher
(`pkill -f nitrosense-watch`, then start it again), since the installer does not touch a running
one.

---

## Using the dashboard

Closing the window only closes the GUI. The service keeps your settings and keeps recording.
The last tab you used and the temperature unit (°C/°F) are remembered per user.

### Início (Home)
Temperature gauges for the CPU and GPU with fan RPM and power in watts, GPU load, and a status
chip: **Desempenho normal**, **CPU limitada por calor** or **no limite de potência**, with the CPU
clock (for example "CPU 3,3 de 4,6 GHz") and the temperature where the processor starts
protecting itself. A banner on top shows the most serious [alert](#alerts).

### Cenário (Scenario)
- **Power plan**: separate plans for AC and battery, shown as *Silencioso* (Power Saver),
  *Equilibrado* (Balance) and *Desempenho* (High-Performance), switched automatically when you
  plug or unplug the charger.
- **Fan control**: **Auto** (the firmware decides), **Max**, **Custom** (CPU and GPU sliders,
  0–100 % in 10 % steps, each with its own Auto switch), **Curve** and **CoolBoost** (higher
  maximum speed in Auto mode only).
- **Curve**: drag the points of a temperature/speed graph, or pick *Silencioso*, *Equilibrado*
  or *Desempenho*. The service follows the hottest of the CPU and the awake GPU every 2 s and
  drives both fans. A dashed line shows the current temperature. With **Curvas separadas para cada
  ventoinha** on, the CPU fan follows the CPU temperature and the GPU fan the GPU temperature (the CPU's
  while the GPU is asleep); a selector switches between the two curves. See [Safety](#safety) for the
  rules the curve cannot override.

### Discos (Disks)
For each NVMe drive: a health chip (Saudável / Atenção / Crítico), temperature, wear, spare
capacity, hours, data written and read, power cycles, unsafe shutdowns, media errors, a 12-minute
temperature chart, file-system use and advice. SMART needs root, so the service reads it.

### Bateria (Battery)
Health is the full-charge capacity against the design capacity, read from
`/sys/class/power_supply`. Also shown: cycles, charge, power draw and time left (smoothed over the
last minute), voltage and, if the firmware reports it, temperature. Charge and power charts and the
health trend use the history. **Limitar a carga a 80 %** switches the firmware's battery health
mode: charging stops near 80 %, which slows wear when the laptop stays plugged in. The service
re-applies it after every boot and resume.

**Battery calibration**: the firmware charges the battery to 100 %, discharges it and recharges it once,
so the laptop relearns the real capacity (useful when the health looks too low for the cycle count).
It takes several hours. **Iniciar calibração** asks for confirmation and works only with the charger
connected. The firmware turns the 80 % limit off for the duration and the service turns it back on at
the end. The tab shows the phase (charging, waiting, discharging, recharging) and the elapsed time, and
**Cancelar calibração** stops it at any moment.

### Monitoramento (Monitoring)
Live charts of the last 12 minutes (one sample per second) for the CPU and the GPU: temperature
(purple line) and load (lilac area), with the current temperature, load, watts and clock in the
header. If the discrete GPU is powered down the chart says so instead of waking it.

### Processos (Processes)
- The heaviest programs by **CPU** (share of the whole processor), **memory** (private resident
  pages, so shared libraries are not counted per process) and **GPU** (memory and utilisation from
  `nvidia-smi pmon`). Programs with many processes, such as a browser, are one row.
- **O que mantém a GPU dedicada acordada**: the programs holding `/dev/nvidia*` open, which is what
  keeps the discrete GPU from suspending. The service provides this because other users' file
  descriptors need root.

### Histórico (History)
Pick 1 hour, 6 hours, 24 hours, 7 days or 30 days. Charts for CPU, GPU and SSD temperature, CPU and
GPU power with the average, peak and the estimated energy used, CPU frequency with the periods of
thermal throttling shaded red, and a summary of the SSD wear trend. Details of what is recorded
are in [Files and configuration](#files-and-configuration).

### Settings (gear icon)
Sticky keys (GNOME), Windows/menu key lock (in firmware), temperature unit, and the options the
model supports: **Use only the discrete GPU**, **LCD Overdrive** and **keyboard backlight off after
30 s**. Options the firmware does not support are hidden.

### The NitroSense key
The key with the NitroSense logo sends AT scancode `0xf5`, which systemd maps to
`KEY_PRESENTATION` (keycode 425). X11 cannot deliver keycodes above 247, so the desktop never sees
it. The installer therefore adds `/etc/udev/hwdb.d/61-nitrosense.hwdb`, which remaps it to
`prog1` (`XF86Launch1`), and registers a GNOME custom shortcut *NitroSense*: `XF86Launch1` →
`/opt/nitrosense/bin/nitrosense`. On other desktops, bind `XF86Launch1` to that command yourself.
To check what any key sends: `sudo python3 -I tools/keyprobe.py 20` and press it. To re-register
the GNOME shortcut as your user: `cd /opt/nitrosense && python3 -m nitrosense.shortcut install`
(or `remove` / `status`).

---

## Alerts

Alerts appear in a banner on top of the window and as desktop notifications. A notification is
sent when an alert is new or gets worse. With `nitrosense-watch` running it sends them (also with
the window closed), repeats a critical one that persists every 30 minutes, and the window stays
quiet, so you never get a duplicate.

| Source | Attention | Critical |
|---|---|---|
| CPU temperature | 90 °C | 97 °C |
| GPU temperature | 85 °C | 92 °C |
| Fan | | 0 RPM while the temperature is 75 °C or more |
| CPU thermal throttling | 10 s or more in a row | |
| GPU thermal slowdown | 10 s or more in a row (reported by NVML) | |
| SSD wear | 80 % or more | 100 % |
| SSD spare capacity | below 50 % | at or below the drive's threshold |
| SSD critical-warning flags | volatile-memory backup failure | spare, reliability or read-only flags |
| SSD media errors | 1 or more | 10 or more |
| SSD temperature | within 10 °C of the drive's warning limit | at that limit |
| File system | 90 % full | 95 % full |
| Battery | | health below 60 % or cells at 60 °C or more |

Battery *attention* (health below 80 %, 1000 cycles, 50 °C) is shown in the Battery tab but does
not raise a notification, so it does not repeat at every login.

To turn the watcher off for one user, copy `/etc/xdg/autostart/nitrosense-watch.desktop` to
`~/.config/autostart/` and add the line `Hidden=true`.

---

## Safety

The service writes to firmware, so the risky features have guard rails.

**Fan curve** (rules the curve cannot override):
- Speeds are never below 20 %, and a curve must reach 100 % by 90 °C. The service refuses others.
- At **88 °C (CPU)** or **82 °C (GPU, when awake)** the fans go to 100 % whatever the curve says.
  With separate curves the rule stays shared: if either temperature reaches its limit, both fans go
  to 100 %.
- Speed rises at once but falls only after the lower target has held for 8 s, so the fans do not
  hunt up and down.
- If every temperature sensor fails for a few samples, the fans go back to the firmware's
  automatic mode and the curve resumes when the sensors return.
- When the service stops or restarts it hands the fans back to automatic. It restores the curve
  after boot or resume. If the service is killed abruptly the fans keep their last speed until it
  restarts (a few seconds).
- The curve is covered by unit tests against a simulated firmware. Check it on your machine before
  relying on it: choose **Curve**, watch temperatures and RPM under load, and go back to **Auto** if
  anything looks wrong.

**Battery charge limit**: uses the same WMI interface as the `acer-wmi-battery` driver. The service
reads the state back after every change and reports an error if the firmware did not accept it.
`tools/probe_battery.py` is a read-only check for it.

**Battery calibration**: starts only with the charger connected and after a confirmation. The firmware
reports no progress and the `acer-wmi-battery` driver does not handle the end of the cycle, so the
service follows it from the charge level and status: it counts the calibration as finished when the
battery went down to 30 % or less and came back to 99 % or more. It stops it by itself at that point
(and turns the 80 % limit back on if it was on), cancels it if the firmware gives up (for example when
the charger is removed) and ends it after 16 hours as a safety net. The system may show low-battery
warnings during the discharge.

**Discrete GPU**: nothing in the app wakes it. NVML and `nvidia-smi` are used only while the PCI
runtime status is *active*. The thermal-slowdown alert that works with the window closed asks NVML
only when the GPU is already awake **and** at 78 °C or more (read from the firmware sensor, which
does not involve the GPU): a hot GPU is busy, so those reads cannot keep it from suspending.

---

## How it works

```
 nitrosense  (GTK 4, your user)          nitrosense-watch  (your user)
        │  Unix socket, JSON lines              │  same socket
        ▼  /run/nitrosense/nitrosense.sock      ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ nitrosensed (root, Python, systemd)                          │
 │  sensors · fan control and curve · SMART · RAPL · throttling │
 │  history recorder (every 30 s) · persistent state            │
 └──────────────────────────────────────────────────────────────┘
        │ /proc/acpi/call (acpi_call)            │ /sys, /proc, NVMe ioctl
        ▼ \_SB.PC00.WMID.WMBH / WMAA / WMBE      ▼
 Embedded controller / BIOS (fans, sensors, battery)    kernel interfaces
```

| Module | Role |
|---|---|
| `nitrosense/daemon.py` | The root service: socket server with per-connection `SO_PEERCRED` authorisation, persistent state, re-applying settings at boot, after resume and on AC changes, the fan curve, throttle and history threads. |
| `nitrosense/encoders.py` | One pure function per firmware method: turns a setting into the exact 64-bit value Windows NitroSense sends (unit-tested against values from the decompiled IL). |
| `nitrosense/wmi.py` | Resolves the ACPI path from sysfs and calls only the 15 allowed methods, each with a fixed input size. |
| `nitrosense/controller.py` | Call sequences (fan modes, lighting, battery limit, …). |
| `nitrosense/fancurve.py` | The fan curve: validation, interpolation and the safety state machine. |
| `nitrosense/disks.py` | NVMe SMART through the admin ioctl, health assessment and advice. |
| `nitrosense/battery.py` | Battery reading, health assessment, time left. |
| `nitrosense/rapl.py` | CPU power in watts from the RAPL energy counters. |
| `nitrosense/throttle.py` | CPU throttling detection from kernel counters and cooling devices. |
| `nitrosense/sysmon.py` | CPU load; NVIDIA load, temperature, power, clock and slowdown reasons through NVML, only while the GPU is awake. |
| `nitrosense/procs.py` | Per-program CPU and memory from `/proc`, GPU per-program use, and the processes holding `/dev/nvidia*`. |
| `nitrosense/history.py` | The 30-day history: per-day JSON-lines files, bucketing, summaries. |
| `nitrosense/alerts.py` | The alert rules (a pure function shared by the window and the watcher). |
| `nitrosense/watcher.py` | The background notifier (`nitrosense-watch`), talking to the notification daemon over D-Bus. |
| `nitrosense/power.py` | Power plans: CPU governor, boost and power-profiles-daemon. |
| `nitrosense/gui/window.py`, `widgets.py` | The dashboard and its widgets (gauges, charts, the curve editor) and CSS. |
| `nitrosense/extract.py`, `geometry.py`, `iconmaker.py` | Read an optional Windows package (artwork, icon). `gui/controls.py`, `gui/theme.py` and `gui/lighting.py` are helpers and the lighting panel from the original window. |

### Power plan mapping

Windows switches Windows power schemes. Linux has none, so each plan maps to:

| Plan | CPU governor | CPU boost | power-profiles-daemon |
|---|---|---|---|
| Silencioso (Power Saver) | `schedutil` | off | `power-saver` |
| Equilibrado (Balance) | `schedutil` | on | `balanced` |
| Desempenho (High-Performance) | `performance` | on | `performance` (or `balanced` if your system has no performance profile) |

---

## Files and configuration

| Path | Purpose |
|---|---|
| `/opt/nitrosense/` | program (`bin/nitrosense`, `bin/nitrosensed`, `bin/nitrosense-watch`, the package) |
| `/usr/local/bin/nitrosense` | GUI launcher |
| `/etc/nitrosense/model/` | `Feature.ini`, `HW_Support.ini` of your model |
| `/etc/nitrosense/allowed-users` | users allowed to control the hardware (one per line) |
| `/etc/nitrosense/wmi.json` | optional WMI method-number overrides |
| `/var/lib/nitrosense/state.json` | saved settings (fan mode, fan curve, battery limit, power plans, …) |
| `/var/lib/nitrosense/history/history-YYYYMMDD.jsonl` | one sample every 30 s, 30 days kept |
| `/var/lib/nitrosense/history/smart.jsonl`, `battery.jsonl` | SSD and battery health counters, every 6 h, never pruned |
| `~/.config/nitrosense/gui.json` | per-user GUI preferences (unit, last tab, history range) |
| `/etc/systemd/system/nitrosensed.service` | service unit |
| `/etc/xdg/autostart/nitrosense-watch.desktop` | starts the alert watcher with the desktop session |
| `/etc/modules-load.d/nitrosense.conf` | loads `acpi_call` at boot |
| `/usr/share/applications/io.github.napejoon.NitroSense.desktop` | menu entry (app ID `io.github.napejoon.NitroSense`) |
| `/etc/udev/hwdb.d/61-nitrosense.hwdb` | NitroSense key → `XF86Launch1` |
| GNOME setting `custom-keybindings/nitrosense/` | shortcut: NitroSense key → open NitroSense |

A history sample holds: CPU, GPU and SSD temperature, fan RPM, CPU load, battery charge and power
draw, CPU/GPU/platform power, mean CPU frequency, and the share of the interval spent thermally or
power limited. Missing readings (for example the GPU while it is asleep) are left out, not zeroed.

To let another user control the hardware:

```bash
echo otheruser | sudo tee -a /etc/nitrosense/allowed-users
```

---

## Service API

The service listens on `/run/nitrosense/nitrosense.sock` and takes one JSON object per line. You can
script it, for example from Python:

```python
import sys; sys.path.insert(0, "/opt/nitrosense")
from nitrosense.client import Client
c = Client()
print(c.request("status")["sensors"])   # cpu_temp, gpu_temp, cpu_fan, gpu_fan, cpu_power, igpu_power, sys_power
c.request("set_fan", mode="max")
c.request("set_fan", mode="custom", cpu_percent=60, gpu_percent=40, cpu_auto=False, gpu_auto=False)
c.request("set_fan", mode="auto")
```

| Command | Arguments and reply |
|---|---|
| `status` | none; sensors, `throttle`, `gpu_throttle`, `fan_curve` (live state), saved `state`, firmware state (`hw`), AC status |
| `disks` | none; SMART data per NVMe controller |
| `history` | `range` 1h/6h/24h/7d/30d; bucketed series, summaries, SSD and battery trends |
| `gpu_holders` | none; programs holding `/dev/nvidia*` open |
| `set_fan` | `mode` auto/max/custom/curve, optional `cpu_auto`, `gpu_auto`, `cpu_percent`, `gpu_percent` |
| `set_fan_curve` | `points`: 3–8 `[temperature, percent]` pairs (see [Safety](#safety)); optional `gpu_points` (the GPU fan's curve) and `split` (one curve per fan) |
| `set_fan_speed` | `fan` cpu/gpu, `percent` 0–100 (Custom mode only) |
| `set_coolboost` | `on` |
| `set_battery_limit` | `on` (only if the firmware supports it; refused during a calibration) |
| `start_battery_calibration` / `stop_battery_calibration` | none; starting needs the charger connected; the state is in `status` → `hw.battery_calibration` |
| `set_keyboard` | `keyboard`: `mode` static/dynamic, `brightness` 1–5, `zones_on` [4 bools], `zone_colors` [4 × "#RRGGBB"], `effect` breathing/wave/zoom/shifting/neon, `speed` 1–9, `direction` 1/2, `effect_color` |
| `set_lcd_overdrive` / `set_win_key` / `set_backlight_timeout` | `on` |
| `set_power_plan` | `source` ac/battery, `plan` powersaver/balance/performance |
| `set_gpu_mode` | `discrete_only` (only if supported; takes effect after reboot) |

Replies are `{"ok": true, ...}` or `{"ok": false, "error": "..."}`.

---

## Firmware interface reference

WMI class **AcerGamingFunction**, GUID `7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56`, ACPI
`<WMID>.WMBH(instance, method, buffer)`. The ACPI path is resolved from sysfs: `<WMID>` is
`\_SB.PCI0.WMID` on the AN515-44 and `\_SB_.PC00.WMID` on the ANV15-51, and the object names
(`WMBH`, `WMAA`, `WMBE`) come from each GUID's `object_id`, so they can differ between BIOSes.

| ID | Method | Used for | Input (little-endian) |
|---:|---|---|---|
| 1 | SetGamingProfile | Win key lock, LCD Overdrive | Win key: `0x02 \| on<<24`; Overdrive: `0x10 \| on<<48` |
| 3 | GetGamingProfile | read LCD Overdrive | `0` → state in byte 6 |
| 5 | GetGamingSysInfo | sensors | `0x01 \| index<<8`; index 1 CPU °C, 2 CPU RPM, 6 GPU RPM, 10 GPU °C → value in bytes 1–2 |
| 6 | SetGamingRgbKb | zone colour | `zone(1/2/4/8) \| R<<8 \| G<<16 \| B<<24` |
| 14 | SetGamingFanBehavior | fan mode | `0x9 \| cpu<<16 \| gpu<<22`, per fan 1=auto 2=max 3=custom (Auto `0x410009`, Max `0x820009`, Custom `0xC30009`) |
| 16 | SetGamingFanSpeed | custom speed | `fan(1=CPU, 4=GPU) \| percent<<8` |
| 20 | SetGamingKBBacklight | lighting effect | bytes: mode (0 static, 1 breathing, 2 neon, 3 wave, 4 shifting, 5 zoom), speed 1–9, brightness 0/25/50/75/100, 0x08 for wave, direction 1 right / 2 left, R, G, B |
| 22 / 23 | Set/GetGamingMiscSetting | GPU switch (if supported) | get `9` → 3 = supported; set `0x02 \| (1 dGPU-only / 2 hybrid)<<8` |
| 7 | GetGamingRgbKb | read zone colour | `zone(1/2/4/8)` → `[status, R, G, B]` |
| 21 | GetGamingKBBacklight | read lighting state | → `[status, mode, speed, brightness, 0x08, direction, R, G, B]` |

WMI class **APGeAction**, GUID `61EF69EA-865C-4BC3-A502-A0DEBA0CB531`, ACPI `<WMID>.WMAA`:

| ID | Method | Used for | Input |
|---:|---|---|---|
| 1 | SetFunction | CoolBoost / backlight timeout | CoolBoost `0x07 \| on<<16`; timeout `0x02 \| hotkey<<8 \| 0x80000 \| brightness<<32 \| (on ? 30<<40 : 0)` |
| 2 | GetFunction | read the same | CoolBoost `0x207`; backlight `0x01 \| hotkey<<8 \| 0x80000` |

Battery health control, GUID `79772EC5-04B1-4BFD-843C-61E7F77B6CC9` (the interface of the
`acer-wmi-battery` driver), ACPI `<WMID>.WMBE`:

| ID | Method | Input (bytes) | Output |
|---:|---|---|---|
| 20 | GetBatteryHealth | `[battery 1, query 1, 0, 0]` | byte 0: supported functions (1 = health mode, 2 = calibration); byte 3: health mode on/off; byte 4: calibration on/off |
| 21 | SetBatteryHealth | `[battery 1, function mask (1 = health mode, 2 = calibration), status 0/1, 0 …]` (8 bytes) | 4 bytes; the service confirms by reading the state back |

Every output of the first two classes starts with a status byte (0 = success); the service treats
any other value as an error. For the battery call the result is checked by reading the state back.

Notes by model:

- **AN515-44** (BIOS V1.04): IDs 5, 6, 7, 16, 17, 20 and 21 are implemented in ACPI (`SSDT5`) and were
  checked there. IDs 14, 22 and 23 match the mainline `acer-wmi` driver. ID 1 is forwarded to the BIOS
  by SMI and is confirmed on hardware (Windows-key lock). ID 3 answers Overdrive with `0xFF` in
  byte 6, which this firmware uses for "not supported". Hardware test: 12/12 lighting and fan checks.
- **ANV15-51**: sensors, fan modes and the battery health mode (get and set) work. The keyboard
  backlight command is rejected by the firmware, so `HW_Support.ini` marks the lighting type as 0.
  The GPU temperature (sensor 10) reads 0 while the discrete GPU is suspended.
- `SetGamingLEDBehavior` (zone on/off mask) is answered with status 2 by the AN515-44 BIOS, so a zone
  is turned off by writing its colour as black through `SetGamingRgbKb`.

If your BIOS differs, override the numbers in `/etc/nitrosense/wmi.json`:

```json
{ "methods": { "SetGamingProfile": { "id": 1, "size": 8 } } }
```

`tools/kbtest.py` walks through every lighting mode through the running service. To inspect your own
tables: `sudo bash tools/collect-acpi.sh` (read-only; writes to `tools/acpi-dump/`, which is
git-ignored).

---

## Security model

- Only the service runs as root. The GUI and the watcher run as your user.
- The service accepts connections only from root and the users in `/etc/nitrosense/allowed-users`,
  checked per connection with `SO_PEERCRED`. Those users can read everything the service exposes,
  including the names of the programs that hold the GPU open.
- Requests are validated (types, ranges, `#RRGGBB` colours, fan-curve rules). The service builds the
  firmware input itself; clients never send raw WMI values.
- Only 15 known WMI methods can be called, each with a fixed input size. Unknown commands are
  rejected.
- `acpi_call` can call any ACPI method, but only root can use `/proc/acpi/call`.
- The history is stored under `/var/lib/nitrosense/history/` as plain files readable by every local
  user; it contains sensor readings only.
- The systemd unit runs with `ProtectSystem=full`, `ProtectHome=true`, `PrivateTmp=true` and
  `NoNewPrivileges=true`.

---

## Troubleshooting

**"NitroSense service is not running"**
```bash
systemctl status nitrosensed
journalctl -u nitrosensed -b
sudo systemctl restart nitrosensed
```

**"Hardware interface unavailable: acpi_call kernel module is not loaded"**
```bash
sudo modprobe acpi_call
dkms status | grep acpi-call
mokutil --sb-state
```
With Secure Boot on, the module must be signed by an enrolled MOK. Run
`sudo dpkg-reconfigure acpi-call-dkms` and reboot; if the MOK screen appears, choose *Enroll MOK*.
After a **kernel update**, DKMS rebuilds the module automatically.

**"permission denied"**: add your user to `/etc/nitrosense/allowed-users`.

**A tab says the service is not updated** (history, SMART, power or "gpu_holders" empty): the
running service is older than the window. Run the installer again, or copy the files and
`sudo systemctl restart nitrosensed`.

**No desktop notifications**: check that the watcher runs (`pgrep -f nitrosense-watch`) and that a
notification daemon is running in your session. The window itself notifies only when the watcher is
not running.

**The discrete GPU never sleeps**: open the **Processos** tab, which lists the programs holding it
open. Closing them lets it suspend (`cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status`).

**No power in watts**: RAPL counters are root-only, so the service must run as root and be up to date;
AMD machines are untested. GPU power appears only while the GPU is awake.

**The battery-limit switch is missing**: the firmware did not report the interface. Run
`sudo python3 -I tools/probe_battery.py` to see what it answers.

**Desempenho (High-Performance) seems no different from Equilibrado (Balance)**: on some CPUs power-profiles-daemon has no
*performance* profile. The governor is still switched; check with
`cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor`.

**The NitroSense key does nothing**
```bash
systemd-hwdb query "evdev:atkbd:$(cat /sys/class/dmi/id/modalias)" | grep f5   # expect KEYBOARD_KEY_f5=prog1
cd /opt/nitrosense && python3 -m nitrosense.shortcut status                    # expect XF86Launch1 -> ...
```
If the first line shows `presentation`, run `sudo systemd-hwdb update && sudo udevadm trigger
--sysname-match="event*"`. If the shortcut is missing, run `python3 -m nitrosense.shortcut install`.

**Debug logging**
```bash
sudo systemctl edit nitrosensed     # add:  [Service]  Environment=NITROSENSE_LOG=DEBUG
sudo systemctl restart nitrosensed
journalctl -u nitrosensed -f        # shows every WMI call with its input/output
```

**Read-only check of the hardware path**: `sudo python3 -I tools/probe.py`

---

## Uninstall

```bash
sudo ./uninstall.sh
```

This puts the fans back on **Auto**, restores the Balance (*Equilibrado*) CPU policy, and removes the service, the
program, the alert watcher, the configuration, the history and the saved state. `acpi-call-dkms`
stays installed; remove it with `sudo apt remove acpi-call-dkms` if nothing else uses it.

---

## Development

```bash
# unit tests (125): encoders, daemon against a simulated firmware, disks, battery, history,
# RAPL, throttling, processes and the fan curve
python3 -m unittest discover -s tests -v

# run the dashboard from the source tree against a simulated laptop (no root, no hardware)
python3 tests/fake_hw.py /tmp/ns.sock &
NITROSENSE_SOCKET=/tmp/ns.sock ./bin/nitrosense
```

`tests/fake_hw.py` simulates the firmware (fan modes change the RPM, temperatures drift), SMART data
and CPU power. Variables for demos: `NITROSENSE_FAKE_HISTORY=1` fills seven days of history,
`NITROSENSE_FAKE_WEAR=<percent>` sets the SSD wear, `NITROSENSE_FAKE_THROTTLE=1` pretends the CPU is
being held back.

The window is a single-instance application. To run a second copy next to an installed one, start
it in its own session bus with its own config:
`XDG_CONFIG_HOME=$(mktemp -d) dbus-run-session -- python3 -I bin/nitrosense`.

| Variable | Meaning |
|---|---|
| `NITROSENSE_SOCKET` | service socket the GUI and the watcher connect to |
| `NITROSENSE_MODEL_DIR` | model `.ini` directory (default `/etc/nitrosense/model`) |
| `NITROSENSE_ASSETS` | artwork directory for the original window helpers (default `/usr/share/nitrosense/assets`) |
| `NITROSENSE_LOG` | service log level (`DEBUG`, `INFO`, …) |

---

## Origin and credits

The project started as a port of Acer **NitroSense 3.01.3056** for Windows by
[napejoon](https://github.com/napejoon/nitrosense-linux), made by reading the Windows application
itself:

1. The NitroSense installer holds an `.appxbundle` whose x64 `.appx` has `Win32/NitroSense.exe`, a
   .NET Framework 4.5 **WPF** application; the MSI holds the native service (`PSSvc`) that talks to WMI.
2. The IL of `NitroSense.exe` gave every bit field the app builds, the sensor indices and the
   slider ranges; strings in the service binary map each pipe command to a WMI method name.
3. The laptop's ACPI tables were disassembled with `iasl` to confirm the method numbers, buffer sizes
   and sensor indices in `WMBH`.

**What this fork changed**: the Windows-style window was replaced by the dashboard described above;
the Windows package became optional; and the service gained SMART, history, RAPL, throttling,
battery health and charge limit, the fan curve, process listing and the alert watcher. The firmware
layer (`encoders.py`, `wmi.py`, `controller.py`) is still upstream's work.

---

## Limitations

- **Interface language**: Brazilian Portuguese only.
- **Keyboard lighting**: the service and the API support it (and the ANV15-51 firmware rejects the
  command), but the dashboard has no lighting panel. The panel from the original window is still in
  `nitrosense/gui/lighting.py`, unused.
- **Disks**: NVMe only; SATA/HDD health would need `smartmontools`.
- **Intel-centric sensors**: CPU watts and throttling detection use Intel interfaces; AMD is untested.
- **GPU data**: only while the discrete GPU is already awake; per-program GPU use needs `nvidia-smi`.
- **Platform power** (`psys`) is recorded but not shown: on the ANV15-51 it reads lower than the CPU
  package, so it is not trustworthy there.
- **Not ported** (Windows-only software): Waves MaxxAudio / DTS sound modes, the NVIDIA GeForce
  Experience button, the Planet9 promotion.
- **Power plans** map to Linux CPU policy (see [Power plan mapping](#power-plan-mapping)), not to
  Windows power schemes.
- **Sticky keys** uses the GNOME setting and is hidden on desktops without it.
- **Notifications** need a desktop notification service; the alerts also show in the window.

---

## Disclaimer

Unofficial project, not affiliated with or endorsed by Acer. "Acer", "Nitro", "NitroSense" and
"CoolBoost" are trademarks of Acer Inc. This repository contains no Acer code, firmware or artwork;
the installer reads artwork from a NitroSense package only if you provide one, and the app icon then
comes from NitroSense's own keycap tile (`nitrosense/iconmaker.py` lights the N red like the backlit
key). The fallback icon `data/icons/io.github.napejoon.NitroSense.svg` is original artwork made for
the upstream project. Changing fan and firmware settings is at your own risk.

## License

MIT, see [LICENSE](../LICENSE). The license covers this repository's code only; any NitroSense artwork
the installer extracts stays Acer's and is not redistributed.
